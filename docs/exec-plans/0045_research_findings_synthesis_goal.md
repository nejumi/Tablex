# Research Findings Synthesis Goal

## Goal

Implement Research Findings Synthesis v1 so controlled research runner outputs become first-class, inspectable context for flexible approach planning instead of a fixed modeling recipe.

## Inputs Reviewed

- `docs/exec-plans/0041_research_source_pack_goal.md`
- `docs/exec-plans/0042_cited_agent_evidence_ingestion_goal.md`
- `docs/exec-plans/0043_agent_task_results_workbench_goal.md`
- `docs/exec-plans/0044_controlled_research_runner_stub_goal.md`
- `schemas/agent_context_pack.schema.json`
- Existing Approach Studio, AgentTask planner, AgentContextPack, research source pack, and local research runner stub code.

## Implementation Plan

- Add a backend synthesis service that reads the latest project-scoped `research_plan`, `research_source_pack`, `research_run_manifest`, `research_findings_report`, `source_citation_manifest`, benchmark packs, and baseline strategy plan.
- Store `research_finding_synthesis`, `research_finding_synthesis_report`, and `visualization_spec` artifacts with Evidence, Report, and Lineage records.
- Expose `POST /api/projects/{project_id}/approach/research-synthesis`.
- Include the latest synthesis summary, citation audit, follow-up requirements, and handoff notes in AgentTaskContract inputs.
- Include the latest synthesis in AgentContextPack payloads and lineage.
- Reference synthesis as a ResearchBrief source and Idea contract input without forcing a fixed baseline or modeling recipe.
- Add Approach UI controls for generation, preview, and download.
- Extend integration tests to verify the synthesis endpoint and downstream handoff.

## Technical Stack

- FastAPI endpoint with synchronous MVP job execution.
- SQLAlchemy metadata models already present for Artifact, Report, Evidence, VisualizationSpec, Job, and LineageEdge.
- Local artifact store for JSON and Markdown outputs.
- React/Vite Approach UI using existing artifact preview/download APIs.

## Implemented Scope

- Research synthesis artifact and Markdown report generation.
- Citation audit summary for source count, citation count, external network access, and connector credential materialization.
- Follow-up requirements that preserve validation/test leakage guards, EvaluationSpec/SplitManifest respect, citation requirements, and runner source policy.
- AgentTaskContract planning inputs and AgentContextPack context slots.
- ResearchBrief source inclusion and Idea contract propagation.
- Approach UI panel for Research Syntheses.
- API integration test coverage.

## Deferred Scope

- Real external web/literature retrieval.
- Ranking or confidence scoring of live external sources.
- Human approval workflow for accepting synthesis conclusions.
- Rich visualization rendering beyond the existing stage-status spec.
- Automatic synthesis regeneration after every upstream artifact change.

## Risks And Open Decisions

- Stub-only research findings are weak evidence and must remain visibly marked as such.
- Future live research runners need strict citation validation and network policy enforcement before synthesis can support decision-grade claims.
- The synthesis intentionally informs AgentRunner choices but does not prescribe a fixed modeling approach. Strong baselines and specialized feature strategies should still be selected from project data, evaluation constraints, Skills, and current research context.
