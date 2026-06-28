# Cross-project Asset Library Goal

## Goal

Separate reusable cross-project knowledge from project-specific prediction workspaces. Skills, FeatureRecipes, EvaluationPatterns, PromptTemplates, and VisualizationTemplates should be registered as versioned assets, backed by artifacts, and attachable to Projects or Ideas through explicit AssetReferences.

## Implemented Scope

- Added API schemas for Asset, AssetVersion, and AssetReference flows.
- Implemented cross-project asset seeding with default assets:
  - `skill`
  - `feature_recipe`
  - `evaluation_pattern`
  - `prompt_template`
  - `visualization_template`
- Added API endpoints:
  - `POST /api/assets/seed-defaults`
  - `GET /api/assets`
  - `POST /api/assets`
  - `GET /api/assets/{asset_id}/versions`
  - `GET /api/projects/{project_id}/asset-references`
  - `POST /api/projects/{project_id}/asset-references`
  - `GET /api/ideas/{idea_id}/asset-references`
  - `POST /api/ideas/{idea_id}/asset-references`
- Stored AssetVersion payloads as cross-project artifacts with `project_id=None`.
- Added lineage edges from Project/Idea to referenced library assets.
- Added Library tab to the frontend.
- Added seed and project-reference actions in the UI.
- Extended integration tests for seed assets, version lookup, Project references, Idea references, and artifact preview.

## Design Decision

The MVP uses existing `Asset`, `AssetVersion`, and `AssetReference` tables. No new table was added. AssetVersion content is artifact-backed so that reusable knowledge remains inspectable through the same artifact browser and content hash path as project outputs.

## Deferred Scope

- Asset editing and new version creation from the UI.
- Asset approval, deprecation, and compatibility policies.
- Skill execution and version locking inside real AgentRunner workspaces.
- Search, filtering, and semantic recommendation of assets for an Idea.
- Cross-project asset import/export.

## Risks And Open Decisions

- Seed assets are initial defaults, not curated production content.
- Asset references are locked but not yet governed by approval workflows.
- The UI currently supports Project-level references; Idea-level references are available through API and covered by tests.
