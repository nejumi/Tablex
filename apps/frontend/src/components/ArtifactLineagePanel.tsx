import React from "react";
import { GitBranch } from "lucide-react";
import type { LocaleMessages } from "../copy";
import type { ArtifactPreviewLineageEdge } from "../types";

export function ArtifactLineagePanel({
  inputs,
  outputs,
  text
}: {
  inputs: ArtifactPreviewLineageEdge[];
  outputs: ArtifactPreviewLineageEdge[];
  text: LocaleMessages;
}) {
  if (!inputs.length && !outputs.length) return null;
  return (
    <div className="artifact-lineage-panel">
      <div className="artifact-lineage-head">
        <GitBranch size={15} />
        <strong>{text.artifactLineageTitle}</strong>
      </div>
      <div className="artifact-lineage-grid">
        <ArtifactLineageList title={text.artifactLineageInputs} edges={inputs} />
        <ArtifactLineageList title={text.artifactLineageOutputs} edges={outputs} />
      </div>
    </div>
  );
}

function ArtifactLineageList({ title, edges }: { title: string; edges: ArtifactPreviewLineageEdge[] }) {
  return (
    <div className="artifact-lineage-list">
      <span>{title}</span>
      {edges.length ? (
        edges.map((edge) => (
          <div className="artifact-lineage-edge" key={edge.edge_id}>
            <strong>{edge.label}</strong>
            <small>
              {edge.relation_type.replace(/_/g, " ")} · {edge.endpoint_asset_type.replace(/_/g, " ")}
            </small>
          </div>
        ))
      ) : (
        <small>-</small>
      )}
    </div>
  );
}
