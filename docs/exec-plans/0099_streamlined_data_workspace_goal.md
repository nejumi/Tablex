# 0099 Streamlined Data Workspace Goal

Date: 2026-06-30

## Goal

Reduce Data tab cognitive load without removing capability. Users should see the primary data and relational evidence surfaces first, while heavy benchmark/source details stay available but secondary.

## Implemented

- Added optional `className` support to the shared `Panel` component.
- Gave Data tab primary panels explicit visual order:
  - Dataset Upload
  - Relational Map
  - Dataset Snapshots
  - Profile Readiness
  - Data Quality Preview
  - Source Artifacts
- Collapsed the large Benchmark Dataset Catalog behind supporting details.
- Preserved existing import, fixture, Kaggle probe, inventory, download, flow, smoke, scenario, and source actions.

## Design Notes

- This is a visual-order and disclosure pass, not a data-model change.
- Relational evidence should be visible before benchmark operations because it answers "what is this data structure?" before "what else can I import?"
- Raw artifacts and long catalogs are still available, but they should not be the first reading task.

## Follow-Up

- Convert the Data tab into a true `Now / Map / Sources / Details` layout instead of a long panel stack.
- Add Agent Chat commands for "show sources", "hide benchmark catalog", and "focus relational map".
