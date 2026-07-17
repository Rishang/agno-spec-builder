# agno-spec-builder

Standalone declarative builder for Agno runtime graphs. It converts YAML or Python mappings into agents, teams, workflows, skills, MCP configuration, knowledge bases, context providers, learning machines, schedules, and Pydantic input/output schemas.

The package does **not** import the parent application's `src` package. It defaults to an Agno `InMemoryDb`, an in-memory skill cache, and an in-memory workflow fan-out state store; applications can inject persistent implementations.

## Install

```bash
pip install ./agno-spec-builder
# Knowledge writer tools additionally use httpx:
pip install './agno-spec-builder[knowledge]'
```

Install the SDK for each LLM/vector provider you select. Provider modules are imported only when selected, and resolved classes are cached after the first import.

## Build a graph

```python
from pathlib import Path

from agno_spec_builder import build

runtime = build(Path("config.yml"))
agent = runtime.agents["researcher"]
workflow = runtime.workflows["research-flow"]

# Runtime-owned MCP execution (uses runtime.mcp_servers)
result = await runtime.mcp_runner.invoke(agent, "Research this topic")
```

A minimal spec:

```yaml
models:
  fast:
    provider: openai
    id: gpt-4o-mini

skills:
  - name: concise
    content: |
      ---
      name: concise
      description: Write concise responses
      ---
      Prefer short, direct answers.

agents:
  - name: Researcher
    slug: researcher
    model: {id: fast}
    skills: [concise]

teams:
  - name: Research Team
    members: [researcher]

workflows:
  - name: Research Flow
    steps:
      - name: research
        run: agent.researcher

mcp:
  - name: local-tools
    type: stdio
    command: python ./server.py
```

`build()` accepts a parsed dictionary, a prevalidated `BaseSchema`, inline JSON/YAML text, a JSON filename string, or a `pathlib.Path` to a JSON/YAML file. Plain strings that are not JSON filenames are treated as document content; use `Path("config.yml")` rather than `"config.yml"` for a YAML file. Every input is validated through `BaseSchema` before any runtime object is constructed. Unknown root keys, malformed catalogs, and duplicate component identities fail immediately with a Pydantic validation error.

```python
from agno_spec_builder import BaseSchema, build

spec = BaseSchema.model_validate(raw_config)
runtime = build(spec)
```

The authoritative root keys are `project`, `providers`, `models`, `embedders`, `vectordb`, `skills`, `mcp`, `schemas`, `agents`, `teams`, `workflows`, `context`, `knowledge`, `learning`, `schedules`, and `tests`. `models` and `embedders` accept the canonical named-list form or the legacy name-to-config mapping. `project`, top-level `vectordb`, and `tests` are retained on the returned `Built` object even though they do not directly construct components.

Optional `build()` arguments are `db`, `skills_cache`, `tenant_namespace`, and `fanout_store`. The returned `Built` object contains all built objects and validated catalogs plus the graph-owned `db`, `schemas`, and `mcp_runner`.

## Extension registries

Registries are public and mutable before calling `build()`:

```python
from agno_spec_builder.builders.agents import MODEL_PROVIDERS
from agno_spec_builder.tools import TOOL_REGISTRY

MODEL_PROVIDERS["company"] = "company_ai.models:CompanyModel"
TOOL_REGISTRY["tickets"] = company_ticket_toolkit
```

Additional registries are available from their owning modules: `EMBEDDERS`, `VECTOR_DBS`, and `RERANKERS` in `builders.knowledge`; `CONTEXT_PROVIDERS` in `builders.context`; and `HOOK_REGISTRY`/`TOOL_HOOK_BUILDERS` in `hooks`. Import targets use `module:ClassName` syntax and are resolved through the package's cached lazy importer.

## Examples

See [`examples/example.py`](examples/example.py) for the single self-contained dictionary spec with validation, graph construction, and extension imports.

## Package boundary

This codebase owns:

- config schemas for agents, teams, workflows/steps, models, providers, embedders, skills, MCP, knowledge, context, learning, and schedules;
- component builders and top-level orchestration;
- default tool and hook registries, Bash and knowledge tools;
- inline/GitHub skill loaders and an injectable cache contract;
- MCP toolkit/runner and graph-local server catalogs;
- CEL/JMESPath workflow compilation and injectable resumable fan-out state.

Application routing, persistence models/migrations, queue tasks, tenant runtime, HTTP endpoints, and scheduler execution remain application responsibilities. This separation lets the parent project consume this package later without coupling the package back to `src`.
