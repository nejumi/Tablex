# Goal 0050: Relational Evidence Reporting Surface

## Objective

Fold relational feature plan, recipe preview, and scenario diagnostics into the normal in-product reporting surfaces so users can understand multi-table readiness without manually chasing raw artifacts.

## Implemented Scope

- Extended Benchmark Evidence Pack entries with `relational_features` summaries.
- Added Relational recipe and Relational diagnostics stages to benchmark evidence readiness.
- Added relational recipe/diagnostics counts and scenario/deferred summaries to the Benchmark Evidence report.
- Added Decision Dashboard relational readiness context and stage.
- Added relational feature risks to the Decision risk register.
- Added Relational Feature Context sections to Decision Reports and drafted Project Reports.
- Extended Home Credit tiny integration coverage across evidence pack, decision report, and project report surfaces.

## Deferred Scope

- Full UI chart specialization for relational scenario comparisons.
- Deployment-grade feature availability certification.
- Automated ranking of relational scenarios by measured model lift.

## Risks And Open Decisions

- Reporting uses artifact metadata and preview diagnostics; it is intentionally not a model performance claim.
- Projects with many benchmark artifacts may need richer filtering by benchmark id and artifact lineage.
