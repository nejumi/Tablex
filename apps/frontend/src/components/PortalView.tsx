import React from "react";
import { BarChart3, Lightbulb, Loader2, Plus } from "lucide-react";
import type { LocaleMessages } from "../copy";
import type { PortalIdea, PortalOverview, Project } from "../types";
import { EmptyInline, Metric } from "./Primitives";

function numberFromSummary(value: unknown, fallback: number | string): number | string {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function projectInProgressForPortal(project: Project): boolean {
  return ["AUTONOMOUS_LOOP", "UNDERSTANDING_REVIEW"].includes(project.current_phase);
}

function formatPortalWorkflowState(value: string | null, text: LocaleMessages) {
  if (!value) return "-";
  const normalized = value.toLowerCase();
  if (normalized === "idle") return text.workflowIdle;
  if (normalized === "draft") return text.workflowDraft;
  if (normalized === "understanding_review") return text.workflowUnderstandingReview;
  if (normalized === "autonomous_loop") return text.workflowAutonomousLoop;
  return value
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function PortalView({
  projects,
  overview,
  ideas,
  text,
  onOpenProject,
  onAddIdea
}: {
  projects: Project[];
  overview: PortalOverview | null;
  ideas: PortalIdea[];
  text: LocaleMessages;
  onOpenProject: (projectId: string) => void;
  onAddIdea: (text: string) => Promise<void>;
}) {
  const [draft, setDraft] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const summary = overview?.summary ?? {};
  const activeCount = projects.filter(projectInProgressForPortal).length;
  const projectCount = projects.length;
  const jobCount = numberFromSummary(summary.job_count, "Project tabs");
  const artifactCount = numberFromSummary(summary.artifact_count, "Workbench");
  const recentProjects = [...projects]
    .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))
    .slice(0, 6);
  const recentUpdates =
    overview?.recent_updates?.length
      ? overview.recent_updates
      : recentProjects.map((project) => ({
          type: "project",
          project_id: project.id,
          title: project.name,
          summary: formatPortalWorkflowState(project.current_phase, text),
          created_at: project.updated_at,
          target_tab: "Overview"
        }));
  const primaryUpdates = recentUpdates.slice(0, 3);
  const secondaryUpdates = recentUpdates.slice(3, 10);

  async function addIdea(event: React.FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      await onAddIdea(value);
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="portal-grid">
      <div className="portal-hero">
        <div>
          <div className="eyebrow">{text.portal}</div>
          <h2>{text.projectPortfolio}</h2>
          <p>{text.portalSubtitle}</p>
        </div>
        <img src="/mascot/tablee-success.svg" alt="" aria-hidden="true" className="portal-mascot" />
      </div>

      <section className="metric-grid compact" aria-label={text.atAGlance}>
        <Metric label={text.totalProjects} value={projectCount} />
        <Metric label={text.activeProjects} value={activeCount} />
        <Metric label={text.totalJobs} value={jobCount} />
        <Metric label={text.totalArtifacts} value={artifactCount} />
      </section>

      <section className="two-column">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <BarChart3 size={17} />
              <h2>{text.recentUpdates}</h2>
            </div>
          </div>
          <div className="portal-project-list">
            {primaryUpdates.map((update, index) => (
              <button
                key={`${update.type}-${update.project_id ?? "cross"}-${index}-${update.created_at}`}
                className="portal-project-card"
                onClick={() => {
                  if (update.project_id) onOpenProject(update.project_id);
                }}
                type="button"
                disabled={!update.project_id}
              >
                <span>
                  <strong>{update.title}</strong>
                  <small>{update.summary} · {new Date(update.created_at).toLocaleString()}</small>
                </span>
                {update.project_id ? <span className="secondary-button">{text.openProject}</span> : null}
              </button>
            ))}
          </div>
          {secondaryUpdates.length ? (
            <details className="supporting-details portal-update-more">
              <summary>
                <span>{text.viewDetails}</span>
                <small>
                  {secondaryUpdates.length} {text.olderUpdates}
                </small>
              </summary>
              <div className="portal-project-list compact">
                {secondaryUpdates.map((update, index) => (
                  <button
                    key={`${update.type}-${update.project_id ?? "cross"}-${index + 3}-${update.created_at}`}
                    className="portal-project-card"
                    onClick={() => {
                      if (update.project_id) onOpenProject(update.project_id);
                    }}
                    type="button"
                    disabled={!update.project_id}
                  >
                    <span>
                      <strong>{update.title}</strong>
                      <small>{update.summary} · {new Date(update.created_at).toLocaleString()}</small>
                    </span>
                    {update.project_id ? <span className="secondary-button">{text.openProject}</span> : null}
                  </button>
                ))}
              </div>
            </details>
          ) : null}
        </div>

        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Lightbulb size={17} />
              <h2>{text.ideaInbox}</h2>
            </div>
          </div>
          <p className="muted-copy">{text.ideaInboxHint}</p>
          {error ? <div className="banner danger">{error}</div> : null}
          <form className="portal-idea-form" onSubmit={addIdea}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={text.ideaInboxPlaceholder}
              rows={4}
            />
            <button className="primary-button" disabled={busy || !draft.trim()}>
              {busy ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}
              {text.addIdea}
            </button>
          </form>
          <div className="portal-idea-list">
            {ideas.length ? (
              ideas.slice(0, 8).map((idea) => (
                <div className="portal-idea" key={idea.id}>
                  <p>{idea.text}</p>
                  <small>{new Date(idea.created_at).toLocaleString()}</small>
                </div>
              ))
            ) : (
              <EmptyInline text={text.noIdeasYet} />
            )}
          </div>
        </div>
      </section>
    </section>
  );
}
