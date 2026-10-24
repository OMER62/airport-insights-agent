# Project scope

This project provides a local conversational interface to prepared public aviation
data. It helps users compare airports and identify candidates for further research.

The implemented capabilities are airport lookup, historical passenger growth,
operational pressure, outbound long-haul share, demand/capacity indicators, and
terminal-expansion screening. Calculations run in Python against a read-only SQLite
snapshot; Gemini selects tools and explains the returned evidence.

The application does not estimate investment returns, establish expansion
feasibility, measure actual terminal capacity, or prove infrastructure causation.
Raw-source ingestion is a separate preparation workflow rather than part of chat.

See the [technical design](tech-design.md) for implementation details and the
[question catalog](test-set.md) for evaluation scenarios, including capabilities
that exceed the current tools.
