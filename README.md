# agno-spec-builder

Standalone declarative builder for Agno runtime graphs. It converts YAML or Python mappings into agents, teams, workflows, skills, MCP configuration, knowledge bases, context providers, learning machines, schedules, authenticated webhooks, and Pydantic input/output schemas.

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

The authoritative root keys are `project`, `providers`, `models`, `embedders`, `vectordb`, `skills`, `toolsets`, `mcp`, `schemas`, `agents`, `teams`, `workflows`, `context`, `knowledge`, `learning`, `schedules`, `webhooks`, and `tests`. `models` and `embedders` accept the canonical named-list form or the legacy name-to-config mapping. `project`, top-level `vectordb`, and `tests` are retained on the returned `Built` object even though they do not directly construct components.

## Workflow routers

Use a keyed `branches` mapping for the simplest Agno-native Router. The branch key is automatically used as the nested step name, so `name` is optional inside the mapping:

```yaml
- name: research_route
  router: 'input.contains("tech") ? "tech" : "finance"'
  branches:
    tech:
      run: agent.tech-researcher
    finance:
      run: agent.finance-researcher
```

Agno exposes `input`, `previous_step_content`, `previous_step_outputs`, `additional_data`, `session_state`, and the available choice-name list as `step_choices` to Router CEL selectors. For example, `router: 'step_choices[input.contains("deep") ? 1 : 0]'` selects by branch position without repeating names.

Use `router: true` for selector-free HITL routing in which Agno asks the user to choose a route. It implicitly enables user input, and `message` is the compact prompt alias:

```yaml
- name: choose_route
  router: true
  message: Choose a research path
  branches:
    tech: {run: agent.tech-researcher}
    finance: {run: agent.finance-researcher}
```

Use the optional `hitl` mapping for compact advanced settings:

```yaml
- name: choose_route
  router: true
  branches:
    tech: {run: agent.tech-researcher}
    finance: {run: agent.finance-researcher}
  hitl:
    message: Choose one or more research paths
    allow_multiple_selections: true
    max_retries: 3
    on_reject: retry
```

Selector-based Routers use a non-empty CEL string and cannot use `message` or `hitl`. Existing explicit Agno fields remain supported for compatibility: `requires_confirmation`, `confirmation_message`, `requires_user_input`, `user_input_message`, `allow_multiple_selections`, `user_input_schema`, `requires_output_review`, `output_review_message`, `hitl_max_retries`, `on_reject` (`skip`, `cancel`, or `retry`), and `human_review`. Do not combine compact aliases with their explicit equivalent (for example, `message` and `user_input_message`).

The list-form `choices` grammar remains available for advanced and backward-compatible declarations. Choices are compiled recursively, so regular steps, Loops, Parallel nodes, and nested Routers retain native Agno behavior:

```yaml
- name: research_router
  router: 'step_choices[input.contains("deep") ? 1 : 0]'
  choices:
    - name: quick_research
      run: agent.researcher
    - name: deep_research
      repeat:
        - name: research_pass
          run: agent.researcher
      until: current_iteration >= 2
      max_iterations: 3
```

`repeat` maps to Agno `Loop.steps`, `until` maps to its CEL `end_condition`, and `max_iterations` sets its iteration cap. Use either `branches` or `choices` on a Router, not both.

For simpler single-route dispatch, `case` remains available and uses the same keyed `branches` mapping and omitted-name shorthand:

```yaml
- name: research_case
  case: 'plan.effort == "high" ? "deep" : "quick"'
  branches:
    quick:
      run: agent.researcher
    deep:
      run: team.research-team
```

## Background execution

Set `background: true` on an agent, team, or workflow to make it the default when invoking that resource through `Built.arun()`:

```yaml
agents:
  - name: Researcher
    model: {id: fast}
    background: true
```

A non-streaming background invocation returns an Agno `PENDING` run output immediately. Poll the same resource using its run and session identifiers:

```python
import asyncio
from agno.run.base import RunStatus

pending = await runtime.arun("agent.researcher", "Research quantum computing trends")

while True:
    result = await runtime.aget_run_output(
        "agent.researcher",
        pending.run_id,
        session_id=pending.session_id,
    )
    if result and result.status in {RunStatus.completed, RunStatus.error, RunStatus.cancelled}:
        break
    await asyncio.sleep(1)
```

The YAML default can be overridden per call with `background=False` or `True`. Pass `stream=True` together with background execution to request Agno resumable streaming:

```python
events = await runtime.arun(
    "workflow.adaptive-research",
    "Deep research on compiler design",
    background=True,
    stream=True,
)
async for event in events:
    print(event)
```

Resumable SSE requires AgentOS. HTTP clients start the run with `background=true&stream=true`, retain `run_id`, `session_id`, and the latest `event_index`, then reconnect to `POST /agents/{id}/runs/{run_id}/resume` (or the analogous `/teams/` or `/workflows/` route). The per-resource YAML default applies to `Built.arun()`; AgentOS requests remain explicit and must send their own `background` flag. Background execution requires a database: every built resource receives the graph database, but inject a persistent database instead of the default `InMemoryDb` when runs must survive process restarts.

Optional `build()` arguments are `db`, `skills_cache`, `tenant_namespace`, and `fanout_store`. The returned `Built` object contains all built objects and validated catalogs plus the graph-owned `db`, `schemas`, and `mcp_runner`.

## Audio agents

Audio-capable models are passed through to Agno unchanged. Use `modalities` and `audio` on the selected model for native text-and-audio responses, and configure Agno toolkits for transcription, text-to-speech, or research:

```yaml
models:
  audio:
    provider: openai
    id: gpt-audio
    modalities: [text, audio]
    audio: {voice: sage, format: wav}

  podcast:
    provider: openai-responses
    id: gpt-5.2

toolsets:
  - name: transcribe
    type: openai
    init:
      transcription_model: gpt-4o-transcribe
      enable_image_generation: false
      enable_speech_generation: false
  - name: openrouter-tts
    type: openai
    init:
      api_key: ${env.OPENROUTER_API_KEY}
      base_url: https://openrouter.ai/api/v1
      text_to_speech_model: hexgrad/kokoro-82m
      text_to_speech_voice: alloy
      text_to_speech_format: mp3
      enable_transcription: false
      enable_image_generation: false
  - name: podcast-voice
    type: elevenlabs
    init:
      voice_id: JBFqnCBsd6RMkjVDRZzb
      model_id: eleven_multilingual_v2
      target_directory: audio_generations
  - name: research
    type: firecrawl

agents:
  - name: Audio Conversation
    model: {id: audio}
    add_history_to_context: true
  - name: Blog to Podcast
    model: {id: podcast}
    tools: [openrouter-tts, research]
  - name: Transcriber
    model: {id: podcast}
    tools: [transcribe]
```

`openai` is included. The normal `openai` toolset uses Agno's `OpenAITools`; setting `init.base_url` selects the compatible wrapper, which forwards the URL to the OpenAI SDK and yields an `AudioChunkEvent` for every TTS response chunk. Python consumers receive raw bytes; JSON/SSE clients receive the normal Agno base64 serialization. The final success string is the tool result passed back to the model. ElevenLabs and Firecrawl remain lazy optional dependencies: install them only when those `toolsets` are used with `pip install 'agno-spec-builder[audio]'`. Supply media to native Agno runs with `audio=[Audio(content=audio_bytes, format="wav")]`; audio-capable model responses arrive in `RunOutput.response_audio`.

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from agno_spec_builder.tools.openai import AudioChunkEvent

app = FastAPI()


@app.get("/tts")
async def tts(text: str):
    async def generate():
        async for event in await agent.arun(text, stream=True):
            if isinstance(event, AudioChunkEvent):
                yield event.audio[0].content

    return StreamingResponse(generate(), media_type="audio/mpeg")
```

## A2A toolsets

Declare a remote A2A client once, then attach it to an agent through `tools`:

```yaml
toolsets:
  - name: research-agent
    type: a2a
    init:
      url: http://localhost:8080/a2a
      headers:
        Authorization: "Bearer ${env.A2A_TOKEN}"
        X-Tenant: acme

agents:
  - name: Coordinator
    model: {id: fast}
    tools: [research-agent]
```

The A2A toolset exposes an async `ask` tool that sends a message to the configured
endpoint. Its headers support `${env.VAR}` expansion when the graph is built.

Applications can register additional types before calling `build()`:

```python
from agno_spec_builder.tools import TOOLSET_REGISTRY
from my_app.tools import JiraTools

TOOLSET_REGISTRY["jira"] = JiraTools
```

Those entries use `type: jira` and pass the environment-expanded `init` mapping
as constructor keyword arguments. The builder always supplies the YAML toolset
`name` as the toolkit's `name` argument.

## Interactive agent CLI

Run any declared agent in Agno's interactive terminal interface:

```bash
agno-spec-builder examples/example.yml researcher --stream
```

The second argument is the agent slug. Use `--session-id` or `--user-id` to
continue an Agno session or identify the terminal user.

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

## Webhook triggers

When `agentos.enabled` is true, `webhooks` adds authenticated `POST` routes to the
AgentOS FastAPI app. Each trigger optionally matches the incoming JSON body with a
JMESPath expression, then invokes a declared agent, team, or workflow. All matching triggers run
concurrently.

```yaml
webhooks:
  - name: grafana-alerts
    path: grafana-alerts
    secret: ${env.GRAFANA_WEBHOOK_SECRET}
    secret_header: X-Grafana-Token
    triggers:
      - kind: agent
        name: cpu-agent
        match:
          field: alerts[0].labels.alertname
          value: CPUHighUsage
        prompt: |
          Analyze this Grafana alert and recommend remediation:
          {payload}
```

`path` must be a unique route suffix; every endpoint is mounted below
`/webhooks/` (for example, `grafana-alerts` becomes
`/webhooks/grafana-alerts`). `secret_header` defaults to
`X-Webhook-Secret`; its value is compared with the environment-expanded `secret`.
Each trigger's `kind` is `agent`, `team`, or `workflow`; its `name` must match a
slug in the matching catalog. Prompts may contain only the
`{payload}` template variable, which expands to pretty-printed JSON. Invalid JSON
returns 422, invalid secrets return 401, and failed agent calls return a server
error so the sender can retry. A caller-provided `base_app` is preserved and receives
the declared webhook routes.

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

- config schemas for agents, teams, workflows/steps, models, providers, embedders, skills, MCP, knowledge, context, learning, schedules, and webhooks;
- component builders and top-level orchestration;
- default tool and hook registries, Bash and knowledge tools;
- inline/GitHub skill loaders and an injectable cache contract;
- MCP toolkit/runner and graph-local server catalogs;
- CEL/JMESPath workflow compilation and injectable resumable fan-out state.

Persistence models/migrations, queue tasks, tenant runtime, application-specific HTTP endpoints, and scheduler execution remain application responsibilities. Declarative `webhooks` are the exception: they mount configured, authenticated routes on the AgentOS FastAPI app. This separation lets the parent project consume this package later without coupling the package back to `src`.
