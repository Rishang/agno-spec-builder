# STYLE.md

Authoritative coding-style and engineering-practice guide for this repository. It documents **only conventions actually followed in the code** — match them; consistency here beats personal preference. When a rule below cites a file, that file is the canonical example to copy from.

Detected stack: **Python 3.12+** (the entire package), **Pydantic v2** (config layer), **Agno** (host runtime being assembled), **FastAPI** (served surface), **asyncio** (concurrency), **YAML** (the declarative spec DSL + Taskfile), **TOML** (packaging/tooling), and embedded **CEL**/**JMESPath** expression languages. There is no TypeScript/JS, Go, Terraform, Helm, Kubernetes, Docker, or CI configuration in the repo — do not add sections or scaffolding for absent technologies.

---

## Repository layout

```
src/agno_spec_builder/      # the package (single source root)
  __init__.py               # public API: build, build_agentos, Built, BaseSchema
  base_schema.py            # authoritative YAML root model
  builder.py                # orchestration: validate → warm → build → Built
  cli.py                    # `agno-spec-builder -f spec.yml` entry point
  imports.py                # cached lazy `module:attr` resolver
  utils.py                  # tiny shared helpers (expand_env, slugify, resolve, log)
  webhooks.py               # FastAPI routes for declarative inbound webhooks
  schemas/                  # pure Pydantic config models, one per component
  builders/                 # config → live Agno objects, one module per component
  providers/                # thin Agno Model subclasses + provider settings
  tools/                    # built-in Toolkits + TOOL/TOOLSET registries
  hooks/                    # pre/post & tool-hook registries
  skills/                   # skill sources, cache contract, registry, loaders
  mcp/                      # MCP server config + toolkit/runner
  workflow/                 # CEL compilation + fan-out state store
examples/                   # example.py (dict spec) + example.yml + skills/
tests/                      # unittest TestCases, run via pytest
Taskfile.yml pyproject.toml uv.lock README.md AGENTS.md CLAUDE.md STYLE.md
```

Directory contract: **`schemas/` validate, `builders/` construct.** A file in `schemas/` holds a Pydantic model with validation and a `*_kwargs()` accessor and *no build logic*; the matching file in `builders/` turns that config into an Agno object. Keep that split — do not construct Agno objects inside a schema, and do not put validation logic in a builder.

---

## Overall architecture

The package converts a declarative spec (YAML file / dict / JSON / prevalidated `BaseSchema`) into a graph of live Agno runtime objects. One pipeline, in `builder.py`:

**validate the whole root → warm remote/local skills → construct synchronously in a worker thread → return a `Built`.**

- Validation is total and up front (`BaseSchema`, `extra="forbid"`), so a bad spec fails before any object is built.
- Construction is synchronous Agno work wrapped in `asyncio.to_thread`, so the async public API never blocks the caller's loop.
- `Built` is a `@dataclass` holding every constructed object plus the graph-owned `db`, `mcp_runner`, and fan-out store — no module-level globals, so multiple independent graphs coexist in one process.

**Module boundary (load-bearing):** the package must not import a parent application's `src` package. It owns config schemas, builders, default tool/hook registries, skill loaders, the MCP toolkit/runner, and CEL/JMESPath compilation. It does *not* own persistence, queues, tenant runtime, or app HTTP endpoints — those are injected. Everything pluggable defaults to an in-memory implementation the application overrides at `build()`.

---

## Shared engineering principles (all languages)

1. **Validate at the boundary, fail loud, fail early.** The root schema rejects unknown keys, duplicate identities, and dangling cross-references before construction. Runtime lookups raise `ValueError` naming the offending value *and the valid options*.
2. **Extend by data, not by branching.** New capabilities are registry entries (a dict key → factory or import target), never a new `if name == ...` arm.
3. **Optional dependencies stay optional.** Provider/DB/SDK modules import lazily, only when a spec selects them. The package installs and imports with a minimal dependency set.
4. **Inject behind a contract; default to in-memory.** Persistence-shaped collaborators are `Protocol`s with an `InMemory*` default, supplied at the entry point.
5. **Comments justify decisions.** Prose in code explains *why* (an Agno quirk, a protocol constraint, an ordering dependency), never *what*.
6. **Secrets via `${env.VAR}` / `${input:var}`**, expanded at build time — never hard-coded.

---

## Python

Primary language; everything in `src/` and `tests/`.

### Formatting & tooling

- **Python `>=3.12`** (`pyproject.toml`, `target-version = "py312"`).
- **Ruff** formats and lints. Line length **120**. Rule set: `E F I UP B SIM RUF`.
- **`ty`** is the type checker (run via `task lint`, `--respect-ignore-files`). Not mypy, not pyright — though a stray checker false-positive is silenced with a trailing `# pyright: ignore` (see `providers/claude.py:19`).
- One command runs all three: `task lint` → `ruff format .` then `ruff check --fix .` then `ty check --fix`.

### Types

- **Full annotations on every function/method, including return types** — even one-liners (`utils.py:is_identifier`).
- Modern syntax only: `X | None` (never `Optional`), builtin generics `list[str]`/`dict[str, T]` (never `typing.List`), `Self` for validator/fluent returns, `Literal[...]` for closed string enums, `Protocol` for structural contracts.
- **PEP 695 generics:** `def resolve[T](names: list[str], registry: dict[str, T]) -> list[T]:` (`utils.py:52`).
- `TYPE_CHECKING`-guarded imports to break cycles when a type is only needed for annotations (`webhooks.py:15`, importing `Built`).

### Naming

- `snake_case` functions/vars, `PascalCase` classes, `_leading_underscore` for private module functions and instance methods/attributes.
- `UPPER_CASE` for module-level registries (`MODEL_PROVIDERS`, `TOOL_REGISTRY`, `TOOLSET_REGISTRY`, `HOOK_REGISTRY`, `TOOL_HOOK_BUILDERS`) and for the local "explicitly-wired-fields" constant `_WIRE`/`_WIRED`.
- **Async methods mirror their sync twin with an `a` prefix:** `fetch`/`afetch`, `resolve`/`aresolve`, `run`/`arun`, `preload`/`apreload`, `get_run_output`/`aget_run_output`.

### Imports

- **Absolute imports only** (`from agno_spec_builder.builders.agents import build_agent`); no relative imports.
- Grouped stdlib → third-party (agno, pydantic, fastapi) → local `agno_spec_builder.*`, blank-line separated. Ruff `I` enforces order; a recent commit ("Separate stdlib and local imports") shows this is actively maintained.
- **Import heavy/optional SDKs lazily** — inside the function that needs them (`from agno.tools.memory import MemoryTools` in `builders/agents.py:128`) or via `imports.resolve_symbol("module:ClassName")`. Top-of-file imports are for always-present deps only.
- Package `__init__.py` files re-export the public surface and declare `__all__` (`schemas/__init__.py`, top-level `__init__.py`).

### Docstrings & comments

- One-line module docstring on every file stating its purpose (`"""FastAPI routes for declarative inbound webhooks."""`).
- **Class docstrings explain the pattern and invariants**, not a field list — see `TeamBuilder` (`builders/teams.py:16`) documenting lazy recursion + cycle detection.
- Comments explain *why*. They cluster around Agno quirks and hard constraints — e.g. the parser-model rationale in `builders/agents.py:174` (tool-calling and native structured output are mutually exclusive), or the per-call MCP connect rationale in `mcp/toolkit.py:1` (anyio cancel scopes).
- Prefer `# fmt: skip` to hand-align a short literal when Ruff would wrap it unhelpfully (`mcp/toolkit.py:_WIRED`).

### Error handling

- Raise `ValueError`/`ImportError`/`HTTPException` with a message that lists the valid options: `f"Unknown name: {name!r}. Available: {list(registry)}"` (`utils.py:56`).
- **Chain deliberately:** `raise NewError(...) from None` to suppress an expected internal error (`utils.py:37` turning a `KeyError` into a user-facing message), `from exc` to preserve a genuine cause (`imports.py:18`, `webhooks.py:40`).
- **`try/finally` to clean up transient state** so a failure doesn't corrupt it — `TeamBuilder._ensure` discards the in-progress slug on failure (`builders/teams.py:54`).
- Validation lives in Pydantic validators (`@model_validator(mode="after")` raising `ValueError`), not scattered `assert`s.

### Logging

- One module-level logger, `log = logging.getLogger("agno_spec_builder")` in `utils.py`, imported wherever needed.
- `log.info` for lifecycle milestones (`builder.py:203` "building graph from spec"), `log.debug` for per-object detail (`providers/claude.py:21` cache config). `%s`-style lazy args, never f-strings in log calls. No `print` except the CLI's user-facing status lines (`cli.py`) and stderr errors.

### asyncio

- Public API is `async`; the real work is a synchronous `_*_sync` core run through `asyncio.to_thread` because Agno construction is blocking (`builder.py:_build_from_root` / `_build_agentos_sync`).
- Concurrent independent work uses `asyncio.gather` (`builder.py:_warm_skills`, `webhooks.py:58` fanning out matched triggers).
- Cache-fill under concurrency uses **double-checked locking with a per-key `asyncio.Lock`** (`skills/cache.py:MemorySkillCache.aresolve`).
- Streaming returns an async iterator directly (not awaited) while non-streaming awaits — see the deliberate split in `Built.arun` (`builder.py:112`).

### OOP & design patterns

- **Registry + extension-by-mutation** — the core extension mechanism. Capabilities are module-level mutable dicts keyed by a YAML string → a factory or `"module:ClassName"` import target (`MODEL_PROVIDERS` in `builders/agents.py:52`). Callers extend behavior by mutating a registry *before* `build()`. Never add capability with a hard-coded branch.
- **Lazy symbol resolution** — `imports.resolve_symbol` is `@functools.cache`d, resolves `"module:attr"` on first use, and raises a clear `ImportError` telling the user to install the SDK. Reuse it; don't import providers eagerly.
- **Builder shape by need:**
  - Stateless one-shot construction → a **free function** (`build_agent`, `build_model`, `build_knowledge`).
  - Recursive / order-independent construction with cross-refs → a **builder class** (`TeamBuilder`, `WorkflowBuilder`, `SchemaBuilder`) using the `_ensure`/`_build` + `_building`-set idiom: memoize into a `registry`, detect cycles via an in-progress set, `try/finally` so a failed build never strands a slug.
- **Protocol + in-memory default, injected at the boundary** — `SkillCache` (`skills/cache.py`), `FanoutStateStore` (`workflow/store.py`), and Agno's `BaseDb` all have `InMemory*` defaults overridden by passing an implementation into `build()`. New pluggable subsystems follow the same shape.
- **ABC for a required-override contract with a shared async wrapper** — `SkillSource` (`skills/base.py`): `@abstractmethod fetch`, with a concrete `afetch` that `to_thread`-wraps it.
- **Thin Agno subclasses for project defaults only** — `providers/claude.py` is a `@dataclass` subclass of Agno's `Claude` that sets prompt-cache defaults in `__post_init__` and calls `super().__post_init__()`. Keep such subclasses minimal.
- **Custom Toolkits subclass `agno.tools.Toolkit`**, register their callables via `super().__init__(name=..., tools=[self.method])`, and derive a stable default name without network calls (`tools/a2a.py:A2ATools`).
- **`@dataclass` for data holders and simple env-driven settings** — `Built` (`builder.py:44`), `ProviderSettings` reading an env toggle in `__post_init__` (`providers/__init__.py:7`).

---

## Pydantic (config schema layer)

All of `schemas/`, plus `base_schema.py`, `mcp/schema.py`. Pydantic **v2**.

- **`extra=` is a deliberate signal, always commented above `model_config`:**
  - `ConfigDict(extra="allow")` for component configs whose unknown keys pass straight through to an Agno constructor (`AgentConfig`, `ModelConfig`, `StepConfig`, `McpServerConfig`). The comment names *why* passthrough is wanted.
  - `ConfigDict(extra="forbid")` for the root (`BaseSchema`) and compact helper models (`RouterHITLConfig`) — to catch typos loudly.
- **Every field is a `Field(...)` with a `description=`.** Descriptions are full sentences and double as the user-facing documentation of the YAML DSL (`schemas/agent.py` is the reference). Wrap long descriptions in parentheses.
- **Validators:**
  - `@model_validator(mode="after") -> Self` for cross-field defaults and invariants (`AgentConfig.default_slug_from_name`, `McpServerConfig.normalize`, `BaseSchema.unique_catalog_names`).
  - `@field_validator(..., mode="before") @classmethod` for input-shape normalization / legacy-alias handling (`ModelConfig._name_alias_to_id`, `BaseSchema.validate_model_catalog`).
- **The `*_kwargs()` accessor pattern** — every component config exposes a method returning `self.model_dump(exclude=_WIRE, exclude_none=True, exclude_defaults=True)`, where `_WIRE` is the local set of fields the builder handles explicitly. This cleanly separates "specially wired" fields from Agno passthrough (`AgentConfig.agent_kwargs`, `ModelConfig.model_kwargs`, `TeamConfig.team_kwargs`, `StepConfig.step_kwargs`).
- Accept both a **canonical list form** (`- name: x`) and a **legacy mapping form** where it eases migration (`models`/`embedders` in `BaseSchema`), normalizing in a `before` validator.

---

## Agno integration conventions

Agno is the runtime this package assembles; these conventions keep the wiring predictable.

- **Identity: `id == slug`.** Agents/teams are constructed with `id=config.slug` so team delegation/selection and run-tracking stay stable (`builders/agents.py:200`, `builders/teams.py:78`). `slug` defaults to `slugify(name)`.
- **Attach a capability only when declared.** An empty Agno `Skills` loader still exposes skill tools and makes a no-skill agent hallucinate skill names, so skills/tools/hooks are wired only when present (`builders/agents.py:112`).
- **Prefer Agno-native constructs** (`Router`, `Loop`, `Parallel`, `Step`, `FallbackConfig`, `WorkflowTools`) over reimplementing behavior; the builders compile the DSL down to them.
- **Mirror Agno's own precedence** when the DSL exposes overlapping options (e.g. `fallback_config` wins over `fallback_models`, matching Agno — `builders/agents.py:184`).

---

## FastAPI (served surface)

`webhooks.py` (declarative inbound webhooks) and `cli.py` / `builder.py` (AgentOS serving).

- Routes are attached to a **caller-provided or freshly created `FastAPI` app**, never a module-level app instance (`attach_webhook_routes(app, runtime)`).
- Build a closure handler with resolved secrets/expressions captured once, returned by a `_handler(runtime, webhook)` factory — compile JMESPath match expressions ahead of the request, not per call (`webhooks.py:_compiled_triggers`).
- **HTTP failures use `HTTPException` with explicit `status.HTTP_*` constants**: `401` for a bad secret, `422` for invalid JSON. Secret comparison uses `hmac.compare_digest` (constant-time), never `==`.
- Detect route collisions up front and raise (`webhooks.py:66`) rather than silently overriding.
- AgentOS is imported lazily inside `_build_agentos_sync` (optional `agno[os]` extra) and constructed off-loop via `to_thread`.

---

## YAML

Two distinct uses; keep them separate in your mind.

### The spec DSL (the product's config language)

This is the package's primary interface — `examples/example.yml` is the canonical, heavily-commented reference. Conventions the DSL follows:

- **Top-level catalogs are named lists:** `providers`, `models`, `skills`, `agents`, `teams`, `workflows`, `toolsets`, `mcp`, `knowledge`, `context`, `learning`, `schedules`, `webhooks`, `schemas`. Each entry has a unique `name` (or `slug` for agents/teams/workflows).
- **Cross-references by string:** an agent names skills/tools/mcp/knowledge from the top-level catalogs; workflow steps target resources with a **`kind.slug` ref** — `agent.researcher`, `team.research-desk`, `workflow.research-plan`.
- **Compact aliases with an escape hatch to the full form:** `branches:` (keyed map, branch key becomes the nested step name) is the simple path; `choices:` (list) is the advanced/backward-compatible form. `message:`/`hitl:` are compact aliases for the explicit Agno HITL fields. Never mix an alias with its explicit equivalent.
- **Section-banner comments** (`# ------ AGENTS ------`) and inline `#` notes explaining non-obvious choices are expected in example/spec files.
- Secrets always `${env.VAR}`; expressions in `router:`/`when:`/`case:` are CEL, `loop:`/webhook `match.field` are JMESPath.

### Taskfile & other project YAML

- `Taskfile.yml` (go-task) is the task runner. Tasks are lowercase verbs with a `desc:` and a `cmds:` list; commands run through `uv run` (`lint` is the only task today).

---

## TOML (`pyproject.toml`)

- Single source of truth for packaging (hatchling backend, wheel packages `src/agno_spec_builder`), the `agno-spec-builder` console script, dependencies, and all tool config.
- **Dependencies are version-pinned or floored deliberately:** hard-pin infrastructure that must match Agno (`agno[os,sqlite]==2.7.2`, `pydantic==2.13.4`, `mcp==1.28.1`), floor SDKs that are forward-compatible (`openai>=2.46.0`).
- **Optional feature deps live in `[project.optional-dependencies]`**, one extra per capability (`ag-ui`, `dev`), so `pip install '.[dev]'` / `[knowledge]` / `[audio]` pull only what's needed. Add a new optional integration as a new extra, not a core dep.
- Tool config (`[tool.ruff]`, `[tool.ruff.lint]`) lives here, not in separate dotfiles.

---

## Embedded expression languages

- **CEL** (`cel-python`) for boolean/selector logic in `router:`, `when:`, `case:`, `until:`. Compiled in `workflow/cel.py`; Agno exposes `input`, `previous_step_content`, `previous_step_outputs`, `additional_data`, `session_state`, `step_choices` to selectors.
- **JMESPath** for data extraction: workflow `loop:` (list to fan out over) and webhook `match.field`. Compile once and reuse (`webhooks.py:21`), don't recompile per evaluation.

---

## Configuration & secrets management

- **`${env.VAR}`** (environment) and **`${input:var}`** (currently resolved from env, `input:foo` → `FOO`) are expanded recursively at build time by `utils.expand_env`, over strings/dicts/lists. `$$` escapes a literal `$`.
- Expansion is applied to toolset `init`, MCP `headers`/`env`, webhook secrets, and AgentOS db `spec`. A referenced-but-unset variable raises `ValueError` naming the variable — never silently empty.
- Runtime feature toggles read the environment once at import into a `@dataclass` settings object (`ProviderSettings`, env `AGNO_ENABLE_PROMPT_CACHE`).

---

## Dependency management

- **`uv`** manages the environment (`.venv` + `uv.lock` committed). Always run project commands through `uv run` (per repo convention and the Taskfile).
- Add dependencies in `pyproject.toml` and let `uv` update the lockfile; core vs optional placement per the TOML section above. Do not add a new runtime dependency for something a few lines of stdlib can do.

---

## Performance considerations

Real, in-code choices — not speculative:

- Blocking Agno construction runs in `asyncio.to_thread` so the event loop stays free.
- `resolve_symbol` is `@cache`d so a repeated provider import is one lookup.
- Remote skill fetches are pre-warmed concurrently (`asyncio.gather`) before synchronous Agno loaders run, and cached behind a double-checked lock.
- MCP connections are opened/used/closed per call by design (anyio cancel-scope safety); warm-pooling is delegated to an external `agentgateway`, not reimplemented in-process (`mcp/toolkit.py`).
- Per-agent `include_tools`/`exclude_tools` trim per-turn tool schemas to keep prompts small.
- Depth caps are enforced at **build time** to fail fast, mirroring Agno's runtime cap (`_MAX_WORKFLOW_REF_DEPTH` in `builders/workflows.py`).

---

## Common abstractions & extension points

Extend the package by mutating these public registries **before** calling `build()`, or by injecting a `Protocol` implementation into `build()`. Never fork behavior with hard-coded branches.

| Extension point | Location | Keyed by / shape |
|---|---|---|
| `MODEL_PROVIDERS` | `builders/agents.py` | provider name → `"module:ModelClass"` |
| `TOOL_REGISTRY` | `tools/__init__.py` | tool name → `Toolkit`/`Function` instance |
| `TOOLSET_REGISTRY` | `tools/__init__.py` | `type:` → `factory(name=..., **init)` |
| `EMBEDDERS`, `VECTOR_DBS`, `RERANKERS` | `builders/knowledge.py` | name → import target |
| `CONTEXT_PROVIDERS` | `builders/context.py` | name → provider |
| `HOOK_REGISTRY` | `hooks/` (guardrails) | hook name → callable |
| `TOOL_HOOK_BUILDERS` | `hooks/__init__.py` | name → builder callable |
| `SkillCache` (Protocol) | `skills/cache.py` | injected via `build(skills_cache=...)` |
| `FanoutStateStore` (Protocol) | `workflow/store.py` | injected via `build(fanout_store=...)` |
| `BaseDb` (Agno) | — | injected via `build(db=...)` |

Toolset factories are always invoked as `factory(name=<yaml name>, **expand_env(init))`; `init` may not set `name`.

---

## Documentation conventions

- **`README.md`** is the user-facing DSL reference — feature-by-feature with runnable YAML/Python snippets. Update it when the DSL changes.
- **`AGENTS.md`** holds agent execution guidance (commands, architecture map, navigation); **`CLAUDE.md`** is a one-line pointer to it; **this `STYLE.md`** is the single source of truth for coding standards. `AGENTS.md` references it and must not duplicate style rules.
- Skills authored inline in specs follow the **`SKILL.md` front-matter format** (`---\nname:\ndescription:\n---` then body) — see `examples/example.yml` `technical-writer`.

---

## CI/CD & development workflow

- **There is no CI pipeline** (no GitHub Actions / GitLab CI / etc.) in the repo. The quality gate is local: run **`task lint`** (ruff format + ruff check --fix + ty check) and **`uv run pytest`** before finishing a change.
- Git history favors small, single-purpose commits with imperative subjects ("Add CLI to build and serve AgentOS", "Separate stdlib and local imports").
- To serve a spec locally: `uv run agno-spec-builder -f examples/example.yml` (requires `agentos.enabled: true`).
