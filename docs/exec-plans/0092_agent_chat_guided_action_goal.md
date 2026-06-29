# 0092 Agent Chat Guided Action Goal

## Goal

Make Agent Chat feel like an in-product action surface instead of a passive transcript. A user instruction should produce a clear answer, visible Tablex action, and an obvious route to the relevant tab.

## Implemented Scope

- Converted returned chat actions from passive status chips into clickable next-step controls.
- Added automatic routing from successful chat turns to the first valid `target_tab`.
- Kept the backend action contract unchanged and used existing harness-owned metadata.
- Added regression assertions that metric changes route to Evaluation and generic runner handoffs route to Approach.
- Documented that chat actions must carry useful `target_tab` metadata.

## Design Notes

- Chat should not bypass harness ownership. It can apply safe actions or prepare AgentTaskContracts, but approval, evaluation, split manifests, artifacts, and lineage remain product-owned.
- The button label intentionally says where to inspect next, not the artifact id.
- More advanced action execution should grow from explicit, tested intents rather than a broad natural-language router.

## Deferred

- Per-action deep links to a selected entity or artifact preview.
- Streaming runner progress in the same chat message.
- Rich action undo/revision flows.
