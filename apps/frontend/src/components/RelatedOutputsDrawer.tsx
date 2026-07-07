import React from "react";
import { BookOpen, Download, Eye, FileText, GitBranch, Package, Search } from "lucide-react";

export type RelatedOutputKind = "notebook" | "report" | "run" | "pipeline" | "research" | "artifact";

export type RelatedOutputItem = {
  id: string;
  kind: RelatedOutputKind;
  title: string;
  detail: string;
  meta?: string | null;
  status?: string | null;
  onOpen?: () => void;
  downloadUrl?: string | null;
};

export function RelatedOutputsDrawer({
  title,
  downloadLabel,
  emptyText,
  items,
  compact = false
}: {
  title: string;
  downloadLabel: string;
  emptyText: string;
  items: RelatedOutputItem[];
  compact?: boolean;
}) {
  const visibleItems = compact ? items.slice(0, 4) : items;
  return (
    <details className={`related-outputs-drawer ${compact ? "compact" : ""}`} open={!compact && items.length > 0}>
      <summary>
        <span>{title}</span>
        <small>{items.length}</small>
      </summary>
      {visibleItems.length ? (
        <div className="related-output-list">
          {visibleItems.map((item) => (
            <div className={`related-output-item ${item.kind}`} key={item.id}>
              <button disabled={!item.onOpen} onClick={item.onOpen} type="button">
                {relatedOutputIcon(item.kind)}
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </span>
              </button>
              <div className="related-output-meta">
                {item.meta ? <span className="badge muted">{item.meta}</span> : null}
                {item.status ? <span className="badge">{item.status}</span> : null}
                {item.downloadUrl ? (
                  <a className="icon-link" href={item.downloadUrl} title={downloadLabel}>
                    <Download size={14} />
                  </a>
                ) : null}
              </div>
            </div>
          ))}
          {compact && items.length > visibleItems.length ? <span className="related-output-more">+{items.length - visibleItems.length}</span> : null}
        </div>
      ) : (
        <p className="related-output-empty">{emptyText}</p>
      )}
    </details>
  );
}

function relatedOutputIcon(kind: RelatedOutputKind) {
  if (kind === "notebook") return <BookOpen size={15} />;
  if (kind === "report") return <FileText size={15} />;
  if (kind === "run") return <GitBranch size={15} />;
  if (kind === "pipeline") return <Package size={15} />;
  if (kind === "research") return <Search size={15} />;
  return <Eye size={15} />;
}
