# 0069 Tablee Mascot Assets Goal

## Goal

Create a first Tablex mascot asset set from the attached Tablee concept and integrate it into the workbench where it improves warmth, guidance, and product identity without increasing cognitive load.

## Inputs Read

- `tabular_prediction_meta_harness_spec_v2/Tablee.png`
- Existing frontend shell and guided UX surfaces in `apps/frontend/src/main.tsx`
- Existing frontend visual system in `apps/frontend/src/styles.css`
- Image generation skill instructions at `/home/yuya/.codex/skills/.system/imagegen/SKILL.md`

## Product Naming Policy

`Tablex` remains the current working product name. `Tablee` is treated as a working mascot name only. Code, schemas, and durable contracts should not assume either name is final.

## Asset Direction

- Preserve the concept's core signals: layered table sheets, colored tabs, sprout marker, friendly eyes, navy limbs, mint cheeks, curious/helpful posture.
- Keep text out of the graphics so locale packs can control wording.
- Use raster only where richer emotion helps. Use SVG for compact UI, empty states, and crisp scalable surfaces.
- Avoid placing the mascot everywhere. Use it as an in-product guide for next action, chat, and important empty states.

## Generated Assets

- `apps/frontend/public/mascot/tablee-hero.png`: transparent 3D-style raster cutout generated from the concept and chroma-keyed locally.
- `apps/frontend/public/mascot/tablee-avatar.svg`: compact brand/chat avatar.
- `apps/frontend/public/mascot/tablee-curious.svg`: focus guide and question-driven workflow illustration.
- `apps/frontend/public/mascot/tablee-empty.svg`: empty state illustration.
- `apps/frontend/public/mascot/tablee-success.svg`: success state illustration for future completion surfaces.
- `apps/frontend/public/mascot/manifest.json`: asset registry, naming policy, and intended usage.

## UI Integration

- Sidebar brand mark now uses the compact Tablee avatar instead of a text-only `T`.
- First-project empty state uses the empty-state mascot to make the starting point feel guided.
- Focus Guide uses the curious mascot as a small navigation cue.
- Agent Chat uses the avatar to reinforce that Codex interaction stays inside the workbench.
- Strategy Brief uses the richer generated raster asset to add a high-emotion moment without making the whole page decorative.

## Deferred

- Pose-specific generated raster set for reassuring, joyful, and thinking states.
- Dark/light tuned raster variants if the current transparent PNG edge treatment is insufficient in browser screenshots.
- Motion/animation guidelines.
- Automatic mascot selection based on job status or project phase.

## Risks

- The transparent raster came from a magenta chroma-key pass. It should be checked in browser on light and dark themes because fine edges may need regeneration with a true transparent-background prompt.
- Mascot overuse can increase cognitive load. Future additions should be limited to decision points, empty states, and human-facing status summaries.
