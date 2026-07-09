import React from "react";
import { FileText, Loader2, Maximize2, MessageSquare, RefreshCw, Search, X } from "lucide-react";
import { LocaleContext, useLocale } from "../locale";
import type { ArtifactPreview, EvidenceReaderMetric, Job, NativeMarimoSession, TranslationJobOutput, TranslationResult } from "../types";
import { ArtifactLineagePanel } from "./ArtifactLineagePanel";

const apiBase = import.meta.env.VITE_API_BASE ?? "";

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

function EmptyInline({ text }: { text: string }) {
  return <div className="empty-inline">{text}</div>;
}

export function FocusedEvidenceReader({
  id,
  eyebrow,
  title,
  body,
  status,
  statusTone = "muted",
  metrics,
  nextEyebrow = "Next",
  nextLabel,
  nextDetail,
  nextButtonLabel,
  nextDisabled = false,
  onNext,
  previewEyebrow = "Read this first",
  previewTitle = "Evidence preview",
  preview,
  previewError,
  previewLoading,
  previewLoadingLabel = "Loading evidence...",
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
  nextEyebrow?: string;
  nextLabel: string;
  nextDetail: string;
  nextButtonLabel: string;
  nextDisabled?: boolean;
  onNext?: () => void;
  previewEyebrow?: string;
  previewTitle?: string;
  preview: ArtifactPreview | null;
  previewError?: string | null;
  previewLoading?: boolean;
  previewLoadingLabel?: string;
  previewEmpty: string;
  previewSourceType?: "artifact" | "report";
  previewSourceId?: string;
  boundary: string;
}) {
  const { text } = useLocale();
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
          <span>{nextEyebrow}</span>
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
          <div className="eyebrow">{previewEyebrow}</div>
          <h3>{previewTitle}</h3>
        </div>
        {previewError ? <div className="banner danger">{previewError}</div> : null}
        {previewLoading ? (
          <div className="banner muted">
            <Loader2 className="spin" size={16} />
            {previewLoadingLabel}
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
        {preview ? (
          <ArtifactLineagePanel
            inputs={preview.lineage?.inputs ?? []}
            outputs={preview.lineage?.outputs ?? []}
            text={text}
          />
        ) : null}
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

async function waitForJobTranslation(jobId: string): Promise<Job> {
  return waitForJobCompletion(jobId, { timeoutMs: 60_000, label: "Translation job" });
}

export function TranslatablePreview({
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
      const completedJob = await waitForJobTranslation(job.id);
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
      {isMarkdownPreview(preview) && shownPreview ? (
        <MarkdownPreview markdown={shownPreview} />
      ) : (
        <pre className="markdown-preview">{shownPreview}</pre>
      )}
    </div>
  );
}

function isMarkdownPreview(preview: ArtifactPreview): boolean {
  const filename = preview.filename.toLowerCase();
  return preview.content_type === "md" || preview.content_type === "markdown" || filename.endsWith(".md") || filename.endsWith(".markdown");
}

function MarkdownPreview({ markdown }: { markdown: string }) {
  const lines = markdown.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.startsWith("```")) {
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !(lines[index] ?? "").startsWith("```")) {
        codeLines.push(lines[index] ?? "");
        index += 1;
      }
      index += index < lines.length ? 1 : 0;
      blocks.push(<pre className="markdown-code" key={`code-${index}`}>{codeLines.join("\n")}</pre>);
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = renderMarkdownInline(heading[2], `heading-${index}`);
      if (level === 1) blocks.push(<h2 key={`h-${index}`}>{content}</h2>);
      else if (level === 2) blocks.push(<h3 key={`h-${index}`}>{content}</h3>);
      else blocks.push(<h4 key={`h-${index}`}>{content}</h4>);
      index += 1;
      continue;
    }
    if (isMarkdownTableStart(lines, index)) {
      const tableLines = [line];
      index += 2;
      while (index < lines.length && (lines[index] ?? "").includes("|") && (lines[index] ?? "").trim()) {
        tableLines.push(lines[index] ?? "");
        index += 1;
      }
      blocks.push(<MarkdownTable lines={tableLines} key={`table-${index}`} />);
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index] ?? "")) {
        items.push((lines[index] ?? "").replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul key={`ul-${index}`}>
          {items.map((item, itemIndex) => <li key={itemIndex}>{renderMarkdownInline(item, `li-${index}-${itemIndex}`)}</li>)}
        </ul>
      );
      continue;
    }
    const image = /^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)\s*$/.exec(line.trim());
    if (image) {
      blocks.push(<MarkdownImage alt={image[1]} src={image[2]} key={`img-${index}`} />);
      index += 1;
      continue;
    }
    const paragraph: string[] = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      (lines[index] ?? "").trim() &&
      !/^(#{1,4})\s+/.test(lines[index] ?? "") &&
      !/^\s*[-*]\s+/.test(lines[index] ?? "") &&
      !isMarkdownTableStart(lines, index) &&
      !(lines[index] ?? "").startsWith("```")
    ) {
      paragraph.push((lines[index] ?? "").trim());
      index += 1;
    }
    blocks.push(<p key={`p-${index}`}>{renderMarkdownInline(paragraph.join(" "), `p-${index}`)}</p>);
  }
  return <div className="markdown-rendered">{blocks}</div>;
}

function isMarkdownTableStart(lines: string[], index: number): boolean {
  const header = lines[index] ?? "";
  const separator = lines[index + 1] ?? "";
  return header.includes("|") && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(separator);
}

function MarkdownTable({ lines }: { lines: string[] }) {
  const [headerLine, ...bodyLines] = lines;
  const headers = splitMarkdownTableRow(headerLine);
  return (
    <div className="markdown-table-wrap">
      <table className="markdown-table">
        <thead>
          <tr>{headers.map((header, index) => <th key={index}>{renderMarkdownInline(header, `th-${index}`)}</th>)}</tr>
        </thead>
        <tbody>
          {bodyLines.map((line, rowIndex) => (
            <tr key={rowIndex}>
              {splitMarkdownTableRow(line).map((cell, cellIndex) => <td key={cellIndex}>{renderMarkdownInline(cell, `td-${rowIndex}-${cellIndex}`)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function splitMarkdownTableRow(line: string): string[] {
  return line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((cell) => cell.trim());
}

function MarkdownImage({ alt, src }: { alt: string; src: string }) {
  const url = src.startsWith("/api/") ? `${apiBase}${src}` : src;
  return (
    <figure className="markdown-figure">
      <img src={url} alt={alt} />
      {alt ? <figcaption>{alt}</figcaption> : null}
    </figure>
  );
}

function renderMarkdownInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[([^\]]+)\]\(([^)\s]+)\))/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(<code key={`${keyPrefix}-code-${match.index}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={`${keyPrefix}-strong-${match.index}`}>{token.slice(2, -2)}</strong>);
    } else if (match[2] && match[3]) {
      const href = match[3].startsWith("/api/") ? `${apiBase}${match[3]}` : match[3];
      nodes.push(<a key={`${keyPrefix}-a-${match.index}`} href={href} target="_blank" rel="noreferrer">{match[2]}</a>);
    }
    cursor = match.index + token.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

export function isHtmlArtifactPreview(preview: ArtifactPreview | null): boolean {
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

export function isVisualArtifactPreview(preview: ArtifactPreview | null): boolean {
  if (!preview?.preview_available) return false;
  return preview.content_type.startsWith("image/") || preview.content_type === "application/pdf";
}

export function VisualArtifactPreview({ preview }: { preview: ArtifactPreview }) {
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

export function NativeMarimoFrame({
  session,
  onRestart
}: {
  session: NativeMarimoSession;
  onRestart?: (artifactId: string) => Promise<void> | void;
}) {
  const { text } = React.useContext(LocaleContext);
  const [sessionStatus, setSessionStatus] = React.useState(session);
  const [sessionUnavailable, setSessionUnavailable] = React.useState(false);
  const [recovering, setRecovering] = React.useState(false);
  const [recoverAttempt, setRecoverAttempt] = React.useState(0);
  const [expanded, setExpanded] = React.useState(false);
  const url = sessionStatus.proxy_url.startsWith("/api/") ? `${apiBase}${sessionStatus.proxy_url}` : sessionStatus.proxy_url;
  const runtimeError = sessionStatus.runtime?.has_error ? sessionStatus.runtime.error_excerpt : null;
  const nativeStatus = sessionStatus.status;
  const sessionStarting = nativeStatus === "starting";
  const sessionFailed = nativeStatus === "failed";
  const showFrame = nativeStatus === "running" && !sessionUnavailable && !sessionFailed && !recovering;
  const restartSession = React.useCallback(async () => {
    if (!onRestart) return;
    setRecovering(true);
    setSessionUnavailable(false);
    try {
      await onRestart(session.artifact_id);
    } finally {
      setRecovering(false);
    }
  }, [onRestart, session.artifact_id]);
  React.useEffect(() => {
    setSessionStatus(session);
    setSessionUnavailable(false);
    setRecovering(false);
    setRecoverAttempt(0);
  }, [session]);
  React.useEffect(() => {
    let stopped = false;
    async function refreshSessionStatus() {
      try {
        const updated = await api<NativeMarimoSession>(`/api/marimo-sessions/${session.session_id}`);
        if (!stopped) {
          setSessionStatus(updated);
          setSessionUnavailable(false);
        }
      } catch {
        if (stopped) return;
        setSessionUnavailable(true);
        if (onRestart && recoverAttempt === 0) {
          setRecoverAttempt(1);
          setRecovering(true);
          void Promise.resolve(onRestart(session.artifact_id)).finally(() => {
            if (!stopped) setRecovering(false);
          });
        }
      }
    }
    const initialTimer = window.setTimeout(refreshSessionStatus, sessionStatus.status === "starting" ? 250 : 600);
    const interval = window.setInterval(refreshSessionStatus, sessionStatus.status === "starting" ? 600 : 5000);
    return () => {
      stopped = true;
      window.clearTimeout(initialTimer);
      window.clearInterval(interval);
    };
  }, [onRestart, recoverAttempt, session.artifact_id, session.session_id, sessionStatus.status]);
  React.useEffect(() => {
    if (!expanded) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setExpanded(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [expanded]);

  function renderLoadingPanel(isExpanded = false) {
    return (
      <div
        className={`native-marimo-loading-panel${isExpanded ? " expanded" : ""}`}
        role="status"
        aria-live="polite"
        aria-label={text.notebookNativeMarimoLoading}
      >
        <div className="native-marimo-loading-mark" aria-hidden="true">
          <span />
        </div>
        <div className="native-marimo-loading-copy">
          <strong>{recovering ? text.notebookNativeMarimoRecovering : text.notebookNativeMarimoLoading}</strong>
          <p>{text.notebookNativeMarimoLoadingDetail}</p>
        </div>
        <div className="native-marimo-loading-progress" aria-label={text.notebookNativeMarimoLoadingProgress}>
          <span />
        </div>
      </div>
    );
  }

  return (
    <div className="native-marimo-viewer">
      <div className="native-marimo-toolbar">
        <div className="preview-meta">
          <span className="badge">{text.notebookNativeMarimoTitle}</span>
          <span className={runtimeError || sessionFailed ? "badge risk" : "badge muted"}>{sessionStatus.status}</span>
        </div>
        <div className="row-actions">
          {onRestart ? (
            <button className="secondary-button" disabled={recovering} onClick={() => void restartSession()} type="button">
              {recovering ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
              {text.notebookNativeMarimoRestart}
            </button>
          ) : null}
          <button className="secondary-button" onClick={() => setExpanded(true)} type="button">
            <Maximize2 size={16} />
            {text.notebookNativeMarimoFullscreen}
          </button>
          <a className="secondary-button text-link-button" href={url} target="_blank" rel="noreferrer">
            {text.notebookNativeMarimoOpenNewTab}
          </a>
        </div>
      </div>
      {runtimeError ? (
        <div className="banner danger native-marimo-runtime-error">
          <strong>{text.notebookNativeMarimoRuntimeError}</strong>
          <details>
            <summary>{text.viewDetails}</summary>
            <pre>{runtimeError}</pre>
          </details>
        </div>
      ) : null}
      {recovering ? renderLoadingPanel() : null}
      {sessionUnavailable && !recovering ? (
        <div className="banner danger native-marimo-runtime-error">
          <strong>{text.notebookNativeMarimoError}</strong>
          <span>{text.notebookNativeMarimoUnavailable}</span>
        </div>
      ) : null}
      {sessionStarting && !runtimeError && !recovering ? renderLoadingPanel() : null}
      {!expanded && showFrame ? (
        <iframe
          key={url}
          className="native-marimo-frame"
          src={url}
          title={text.notebookNativeMarimoTitle}
          sandbox="allow-scripts allow-same-origin allow-forms allow-downloads allow-popups allow-modals"
        />
      ) : null}
      {expanded ? (
        <div className="native-marimo-expanded" role="dialog" aria-modal="true" aria-label={text.notebookNativeMarimoTitle}>
          <div className="native-marimo-expanded-toolbar">
            <div className="preview-meta">
              <span className="badge">{text.notebookNativeMarimoTitle}</span>
              <span className={runtimeError || sessionFailed ? "badge risk" : "badge muted"}>{sessionStatus.status}</span>
            </div>
            <div className="row-actions">
              {onRestart ? (
                <button className="secondary-button" disabled={recovering} onClick={() => void restartSession()} type="button">
                  {recovering ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
                  {text.notebookNativeMarimoRestart}
                </button>
              ) : null}
              <a className="secondary-button text-link-button" href={url} target="_blank" rel="noreferrer">
                {text.notebookNativeMarimoOpenNewTab}
              </a>
              <button className="icon-button" onClick={() => setExpanded(false)} title={text.close} type="button">
                <X size={18} />
              </button>
            </div>
          </div>
          {runtimeError ? (
            <div className="banner danger native-marimo-runtime-error expanded">
              <strong>{text.notebookNativeMarimoRuntimeError}</strong>
              <details>
                <summary>{text.viewDetails}</summary>
                <pre>{runtimeError}</pre>
              </details>
            </div>
          ) : null}
          {recovering ? (
            renderLoadingPanel(true)
          ) : sessionUnavailable ? (
            <div className="banner danger native-marimo-runtime-error expanded">
              <strong>{text.notebookNativeMarimoError}</strong>
              <span>{text.notebookNativeMarimoUnavailable}</span>
            </div>
          ) : sessionStarting && !runtimeError ? (
            renderLoadingPanel(true)
          ) : showFrame ? (
            <iframe
              key={url}
              className="native-marimo-expanded-frame"
              src={url}
              title={text.notebookNativeMarimoTitle}
              sandbox="allow-scripts allow-same-origin allow-forms allow-downloads allow-popups allow-modals"
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function HtmlArtifactPreview({ preview }: { preview: ArtifactPreview }) {
  const { text } = React.useContext(LocaleContext);
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
      {preview.truncated ? (
        <div className="banner warning">{text.artifactPreviewTruncatedWarning}</div>
      ) : null}
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
