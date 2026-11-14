# ALIBI evidence workbench

> **Historical handoff — superseded November 14 afternoon.** Use [../PRODUCT.md](../PRODUCT.md) and [the current owner instructions](overhaul/START_HERE.md) for this continuation. This file preserves the previous plan/demo; its schedule, setup tasks and product direction must not override the current contract.

Direction selected November 14, 2026. Reference collection was time-boxed to under 20 minutes; no brand assets, hosted fonts, component library or stock imagery is used.

- [GOV.UK editorial paragraphs](https://design-system.service.gov.uk/styles/paragraphs/): one clear lead, short paragraphs, strong hierarchy and restrained small type. ALIBI adapts the editorial rhythm to a compact evidence desk, using system sans and a local Georgia case title rather than the licensed GOV.UK font.
- [GitHub Desktop split diff](https://docs.github.com/en/desktop/making-changes-in-a-branch/committing-and-reviewing-changes-to-your-project-in-github-desktop): compare aligned copies on the same row, retain context around a discrepancy and expand the whole record only on request. A missing host line and its surviving collector copy share the timestamp; exact unabridged text opens in a source drawer.
- [Carbon data table](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines): stable column headers, predictable row structure and progressive disclosure. Status words accompany color; record counts and coverage are expandable, with raw provenance kept close to the evidence.

Use paper `#F4F2EC`, white evidence surfaces, ink `#1D252B`, muted `#59636B`, navy `#264D68`, rust `#A7352E` only for discrepancy/error, and ochre `#846329` for unresolved coverage. Three columns: 200 / flexible / 310 pixels at 1440, 170 / flexible / 280 at 1280. Stack below 760 pixels. Each panel scrolls independently at laptop sizes; the raw drawer preserves lines and scrolls horizontally.

The primary story is an observation, its sources, and the limit of what it establishes. No inferred actor identity, uncalibrated confidence score or generalized accuracy claim is added. Source nodes come from the public manifest; the connecting spine represents their shared evidence bundle, not inferred network traffic. Runtime and tool metadata live in Details. Native modal dialogs provide Escape, focus containment and focus return; reduced-motion settings disable transitions.
