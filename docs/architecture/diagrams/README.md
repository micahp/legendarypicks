# Editable SVG architecture and football schematics

[Architecture](../README.md) · [Gridiron](../GRIDIRON.md) · [Liquid AI](../LIQUID-AI.md)

Standalone SVGs have explicit viewBox dimensions, box widths and label positions; they scale without rasterization. These are conceptual illustrations, not recorded simulation telemetry.

| Diagram | Purpose |
|---|---|
| [Model family](model-family.svg) | Full-label fixed-layout alternative to the shared architecture flow |
| [CEG fit/runtime](ceg-fit-runtime.svg) | Training/inference boundary and generated event lifecycle |
| [Conditioning methods](conditioning-methods.svg) | Four historical row-filtering alternatives |
| [Catch point](catch-point.svg) | Side view of catch-height versus ground-landing pursuit |
| [Player perception](player-perception.svg) | Assigned zone, observed cues and reachable catch opportunity |
| [Check-release](check-release.svg) | Protection, release and proactive contest eligibility |

Use Mermaid for control flow and state transitions; preserve meaningful wording, wrap long labels with explicit line breaks, and split overly wide diagrams. Prefer SVG if the geometry or node width must be exact. Use an opaque neutral background, readable labels, accessible title/description and relative image links. Review desktop and narrow rendered widths; no claim of renderer verification without inspecting the rendered output. Keep schematic geometry distinct from actual traces and measured units.
