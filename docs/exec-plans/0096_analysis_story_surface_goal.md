# 0096 Analysis Story Surface Goal

## Goal

Make notebook and report review feel like a guided analysis story, not a shelf of artifacts. Humans should immediately see what to read, why it matters, what evidence backs it, what caveats remain, and what to ask Codex next.

## Implemented Scope

- Added `analysis_story_surface.v1` at `GET /api/projects/{project_id}/analysis-story`.
- The backend now selects the best current Data Review or analysis notebook story from artifact state.
- The story includes selected preview artifact, read order, visual story cards, evidence cards, caveats, Codex prompts, supporting source summaries, metrics, and raw artifact refs.
- Empty or not-ready model diagnostics are not promoted over Data Understanding.
- The Notebooks tab now opens with one Analysis Story panel, inline preview, and a compact Codex guide.
- Notebook library and raw artifact outputs are kept behind one supporting details drawer.

## Design Notes

- The story surface is an editor layer over artifacts, not a new fixed notebook template.
- Codex remains the flexible author/runner for deeper analysis; the harness only chooses the current reading surface and preserves artifact, lineage, safety, and evaluation boundaries.
- Static notebook evidence still states that notebook cells were not executed, even after safe capture, because the initial capture is harness-rendered evidence.

## Deferred

- Persisting analysis-story snapshots as first-class artifacts.
- Letting Codex dynamically rewrite the story in the user's active locale.
- Replacing the Reports tab supporting shelves with the same story-style progressive disclosure.
