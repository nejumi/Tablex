import React from "react";
import { Copy, Database, Layers, Loader2 } from "lucide-react";
import type { LocaleMessages } from "../copy";
import type { Project } from "../types";

export type ProjectCloneMode = "data_only" | "full";

export function nextProjectCloneName(projectName: string, suffix: string, existingNames: string[]): string {
  const escapedSuffix = suffix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const root = projectName.replace(new RegExp(`\\s+${escapedSuffix}(?:\\s+\\d+)?$`, "iu"), "").trim();
  const base = `${root || projectName} ${suffix}`.trim();
  const occupied = new Set(existingNames.map((name) => name.trim().toLocaleLowerCase()));
  if (!occupied.has(base.toLocaleLowerCase())) return base;
  let index = 2;
  while (occupied.has(`${base} ${index}`.toLocaleLowerCase())) index += 1;
  return `${base} ${index}`;
}

export function ProjectCloneDialog({
  project,
  text,
  existingProjectNames,
  busy,
  onCancel,
  onConfirm
}: {
  project: Project;
  text: LocaleMessages;
  existingProjectNames: string[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: (name: string, mode: ProjectCloneMode) => void;
}) {
  const [name, setName] = React.useState(() =>
    nextProjectCloneName(project.name, text.projectCloneNameSuffix, existingProjectNames)
  );
  const [mode, setMode] = React.useState<ProjectCloneMode>("data_only");

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
        className="delete-project-dialog project-clone-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="clone-project-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="delete-project-title">
          <span className="delete-project-icon clone-project-icon">
            <Copy size={18} />
          </span>
          <div>
            <h2 id="clone-project-title">{text.cloneProjectTitle}</h2>
            <strong>{project.name}</strong>
          </div>
        </div>

        <label className="project-clone-name">
          <span>{text.cloneProjectName}</span>
          <input value={name} maxLength={200} autoFocus onChange={(event) => setName(event.target.value)} />
        </label>

        <fieldset className="project-clone-modes">
          <legend>{text.cloneProjectMode}</legend>
          <label className={mode === "data_only" ? "project-clone-mode selected" : "project-clone-mode"}>
            <input
              type="radio"
              name="clone-mode"
              value="data_only"
              checked={mode === "data_only"}
              onChange={() => setMode("data_only")}
            />
            <Database size={18} />
            <span>
              <strong>{text.cloneProjectDataOnly}</strong>
              <small>{text.cloneProjectDataOnlyDetail}</small>
            </span>
          </label>
          <label className={mode === "full" ? "project-clone-mode selected" : "project-clone-mode"}>
            <input
              type="radio"
              name="clone-mode"
              value="full"
              checked={mode === "full"}
              onChange={() => setMode("full")}
            />
            <Layers size={18} />
            <span>
              <strong>{text.cloneProjectFull}</strong>
              <small>{text.cloneProjectFullDetail}</small>
            </span>
          </label>
        </fieldset>

        <div className="delete-project-actions">
          <button className="secondary-button" disabled={busy} onClick={onCancel} type="button">
            {text.cancel}
          </button>
          <button
            className="primary-button"
            disabled={busy || !name.trim()}
            onClick={() => onConfirm(name.trim(), mode)}
            type="button"
          >
            {busy ? <Loader2 className="spin" size={16} /> : <Copy size={16} />}
            {busy ? text.cloningProject : text.cloneProjectAction}
          </button>
        </div>
      </section>
    </div>
  );
}
