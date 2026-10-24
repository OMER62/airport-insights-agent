# PR TITLE

feat: Add airport investment intelligence agent

---

# PR DESCRIPTION

## The Issue

The repository contains only a project introduction and license on `main`. Analysts need a runnable assistant that compares US airports and identifies candidates for further terminal-expansion research using traceable evidence.

## Root Cause

The data preparation pipeline, deterministic analysis, tool interfaces, conversational UI, prepared database, and validation suite have not yet been committed to the repository.

## The Solution

- Add five ETL tasks for flight activity, flight performance, airport identity, FAA outlook, and Gold SQLite publication.
- Add validated analysis requests, read-only database access, evidence metadata, coverage checks, and deterministic metrics for traffic growth, operational pressure, long-haul share, demand/capacity pressure, and expansion screening.
- Expose six MCP tools and connect them to a Gemini agent through Chainlit, with conversation context, visible evidence, tool limits, and error handling.
- Include the prepared Gold database, loopback-only launcher, environment template, pinned dependencies, tests, runtime/evaluation runners, and architecture and usage documentation.

The existing `PUBLICATION_REVIEW.md` records unresolved dependency security findings, source provenance and redistribution checks, and reproducibility limitations. These remain follow-up work; this PR does not claim release readiness. Live Gemini answer quality is separate from deterministic test coverage.

## Flow Diagram

```text
┌─────────────────────────────┐
│ Raw BTS / FAA / airport data│
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ ETL tasks → Gold SQLite     │
└──────────────┬──────────────┘
               │ read-only evidence
               ▼
┌─────────────────────────────┐
│ start_chat() → MCP tools    │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ handle_message()            │
│ → run_agent() → MCP tools   │
│ → service.analyze()         │
│ → metrics + evidence       │
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│ Gemini explanation          │
│ + visible Chainlit evidence │
└─────────────────────────────┘
```

## Testing

- [x] I have tested this PR on my local machine.
- [x] I have added unit tests for the changes I made.

- `.\.venv\Scripts\python.exe -m ruff check app tests run_app.py` — clean.
- `.\.venv\Scripts\python.exe -m pytest -q` — 294 passed, 10 subtests passed; two upstream deprecation warnings.
- With `PYTHONPATH=app`, `.\.venv\Scripts\python.exe tests/evaluation/validate_runtime.py` — six MCP tools discovered, five database checks passed, Chainlit returned HTTP 200 and HTML.
- Installed `requirements-dev.txt` successfully, including the `literalai` source package. The publication review predates this successful installation and runtime validation.
- Live Gemini evaluation was not run.

## Additional Changes

- [x] Docs changed
- [x] Config changed
- [x] Other: prepared Gold SQLite snapshot
