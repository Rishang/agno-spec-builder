# AGENTS.md

Guidance for coding agents working in this repository. Behavior, workflow, and navigation live here; **all coding standards and conventions live in @STYLE.md — read it before writing code and follow it.**

## Commands

- Python runs through `uv` (`.venv` present) — prefix everything with `uv run`.
- Lint/format/typecheck (all three): `task lint` — `ruff format`, `ruff check --fix`, `ty check --fix`.
- Run all tests: `uv run pytest` (stdlib `unittest.TestCase` classes; pytest discovers them).
- Run one test file / case: `uv run pytest tests/test_builder.py` or `... -k SomeTestName`.
- Serve a spec locally: `uv run agno-spec-builder -f examples/example.yml` (requires `agentos.enabled: true`).

There is no CI — `task lint` + `uv run pytest` are the quality gate. Run both before finishing.

## What this package does (one paragraph)

Converts a declarative spec (YAML / dict / JSON / `BaseSchema`) into a graph of live Agno runtime objects. Pipeline in `builder.py`: **validate the root → warm remote/local skills → construct synchronously in a worker thread → return a `Built`**. `Built` is a dataclass holding every constructed object plus the graph-owned `db`, `mcp_runner`, and fan-out store.

## Where things are

- `base_schema.py` — authoritative YAML root (`extra="forbid"`; validates uniqueness + cross-references).
- `builder.py` — `build()` / `build_agentos()` orchestration and the `Built` result. `Built.arun(target, ...)` takes a `kind.slug` ref (`agent.researcher`, `team.x`, `workflow.y`).
- `schemas/` — Pydantic config models, one per component (**validate only**).
- `builders/` — config → Agno objects, one module per component (**construct only**). `workflows.py` is the deepest: compiles steps into Agno `Step`/`Loop`/`Parallel`/`Router` trees via CEL + JMESPath.
- `providers/`, `tools/`, `hooks/`, `skills/`, `mcp/`, `workflow/` — subsystems; each `__init__.py` exposes its public API and any registries.
- `examples/example.yml` — canonical, fully-commented spec; the best reference for the DSL.

## Hard rules (do not violate)

- **No import of a parent app's `src`.** This package is standalone; persistence/queues/tenant/app-HTTP are injected, and everything pluggable defaults to in-memory. (Full rationale: @STYLE.md → Overall architecture.)
- **Extend via registries/injection, never hard-coded branches.** The registry map and injection points are in @STYLE.md → Common abstractions & extension points.
- **Make code changes match @STYLE.md** for the language/technology you're touching.
