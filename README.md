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

runtime = await build(Path("config.yml"))
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

`build()` is asynchronous and accepts a parsed dictionary, a prevalidated `BaseSchema`, inline JSON/YAML text, a JSON filename string, or a `pathlib.Path` to a JSON/YAML file. Plain strings that are not JSON filenames are treated as document content; use `Path("config.yml")` rather than `"config.yml"` for a YAML file. Every input is validated through `BaseSchema` before any runtime object is constructed. Unknown root keys, malformed catalogs, and duplicate component identities fail immediately with a Pydantic validation error.

```python
from agno_spec_builder import BaseSchema, build

spec = BaseSchema.model_validate(raw_config)
runtime = await build(spec)
```

The authoritative root keys are `project`, `providers`, `models`, `embedders`, `vectordb`, `skills`, `mcp`, `schemas`, `agents`, `teams`, `workflows`, `context`, `knowledge`, `learning`, `schedules`, and `tests`. `models` and `embedders` accept the canonical named-list form or the legacy name-to-config mapping. `project`, top-level `vectordb`, and `tests` are retained on the returned `Built` object even though they do not directly construct components.

Optional `build()` arguments are `db`, `skills_cache`, `tenant_namespace`, and `fanout_store`. The returned `Built` object contains all built objects and validated catalogs plus the graph-owned `db`, `schemas`, and `mcp_runner`.

## Serve with AgentOS and A2A

Enable AgentOS and its Agent-to-Agent (A2A) interface in the spec:

```yaml
agentos:
  enabled: true
  a2a_interface: true
  server:
    host: localhost
    port: 8000
```

Construct and serve the runtime with `build_agentos()`:

```python
from agno_spec_builder import build, build_agentos

runtime = await build("project: demo\nagentos:\n  enabled: true\n  a2a_interface: true")
agent_os = await build_agentos(runtime)
assert agent_os is not None
agent_os.serve(app=agent_os.get_app(), **runtime.agentos.server.model_dump())
```

With A2A enabled, every built resource has an agent card and message endpoints. For
example, an agent named `researcher` is available at:

- `GET /a2a/agents/researcher/.well-known/agent-card.json`
- `POST /a2a/agents/researcher/v1/message:send`
- `POST /a2a/agents/researcher/v1/message:stream`

Use the resource-specific A2A base URL when connecting a client:

```python
import asyncio

from agno.client.a2a import A2AClient


async def main():
    client = A2AClient("http://localhost:8000/a2a/agents/researcher")
    result = await client.send_message(message="Hello!")
    print(result.content)


asyncio.run(main())
```

Teams and workflows use the analogous `/a2a/teams/{id}` and
`/a2a/workflows/{id}` URLs. See the [Agno A2A documentation](https://docs.agno.com/agent-os/interfaces/a2a/introduction)
for authorization scopes and protocol details.

## Serve with AG-UI

Enable the Agent-User Interaction (AG-UI) interface to expose every built
agent and team through a separate streaming UI route:

```yaml
agentos:
  enabled: true
  agui_interface: true
```

An agent named `researcher` receives `POST /agui/agents/researcher/agui`; a
team named `research-team` receives `POST /agui/teams/research-team/agui`.
Each prefix also exposes `GET /status`. AG-UI does not support workflows, so
they are not published by this setting. See the
[Agno AG-UI documentation](https://docs.agno.com/agent-os/interfaces/ag-ui/introduction)
for frontend client integration and event formats.

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
