import React from "react";
import { Loader2, Trash2 } from "lucide-react";
import type { LocaleMessages } from "../copy";
import type { Project } from "../types";

export function ProjectDeleteDialog({
  project,
  text,
  busy,
  onCancel,
  onConfirm
}: {
  project: Project;
  text: LocaleMessages;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  React.useEffect(() => {
    if (busy) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [busy, onCancel]);

  return (
    <div className="delete-project-backdrop" role="presentation" onMouseDown={busy ? undefined : onCancel}>
      <section
        className="delete-project-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-project-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="delete-project-title">
          <span className="delete-project-icon">
            <Trash2 size={18} />
          </span>
          <div>
            <h2 id="delete-project-title">{text.deleteProjectTitle}</h2>
            <strong>{project.name}</strong>
          </div>
        </div>
        <p>{text.deleteProjectConfirm}</p>
        <div className="delete-project-actions">
          <button className="secondary-button" disabled={busy} onClick={onCancel} type="button">
            {text.cancel}
          </button>
          <button className="secondary-button danger" disabled={busy} onClick={onConfirm} type="button">
            {busy ? <Loader2 className="spin" size={16} /> : <Trash2 size={16} />}
            {busy ? text.deletingProject : text.deleteProjectAction}
          </button>
        </div>
      </section>
    </div>
  );
}
