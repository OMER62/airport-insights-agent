# Documentation guide

These documents explain the Airport Investment Intelligence Agent for a technical
reviewer: what each process does, why its decisions matter, what it produces and
where its conclusions stop. Read them in order for the full journey, or start with
the stage relevant to your review.

```mermaid
flowchart LR
    Overview[1. Purpose and architecture] --> Preparation[2. Data preparation]
    Preparation --> Modeling[3. Data modeling]
    Modeling --> Analysis[4. Deterministic analysis]
    Analysis --> Chat[5. Chat and MCP]
    Chat --> Evaluation[6. Testing and evaluation]
```

| Stage | What it explains |
|---|---|
| [Overview and technical design](01-overview/tech-design.md) | System boundaries, source choices, component responsibilities and screening architecture |
| [Data preparation](02-data-preparation/data-preparation.md) | Activity cleaning, scheduled-flight outcomes, airport reconciliation, outlook preparation and publication |
| [Data modeling](03-data-modeling/data-modeling.md) | Layers, grains, canonical identities, Gold relationships, eligible totals and source evidence |
| [Deterministic analysis](04-analysis/analysis.md) | Selection, periods, five metrics, worked examples, eligibility and national scoring |
| [Chat and MCP](05-chat-and-mcp/chat-and-mcp.md) | Tool discovery, a complete question, follow-up history, limits and failure handling |
| [Testing and evaluation](06-testing-and-evaluation/testing-and-evaluation.md) | Test strategy, current checks, prior runtime evidence, live-answer findings and remaining coverage |

The [task definition](01-overview/task-definition.md) records the assignment's
requirements. The [question catalog](01-overview/test-set.md) preserves 30 evaluation
scenarios; it includes capabilities beyond the currently exposed tools.

## Reading the diagrams and examples

Mermaid diagrams show execution order, ownership boundaries and data relationships.
A relationship diagram describes logical connections rather than asserting every
relationship is enforced by database constraints. Worked numerical examples are
illustrative unless the evaluation chapter explicitly identifies a saved result.

Three distinctions matter throughout:

- Source completeness is different from coverage of measurements, airlines or flights.
- Calendar traffic, fiscal boardings and publication edition are separate concepts.
- Screening evidence identifies investigation candidates; it does not measure terminal capacity, unmet demand or investment returns.

The process chapters describe current behavior and significant departures from
earlier proposals. All test results and evaluation findings are consolidated in
the final chapter, with historical evidence distinguished from freshly run checks.

## Public distribution

This repository includes current documentation and the prepared Gold database. Historical research and evaluation archives are retained only in the original draft project. References to those archives describe prior evidence; the archived artifacts are not included here. Raw sources, Silver CSVs, and mapping audit files must be obtained separately to rerun ETL.
