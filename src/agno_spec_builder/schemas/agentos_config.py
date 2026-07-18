"""AgentOS runtime configuration — declarative spec for serving a built graph via
Agno's AgentOS.

This schema is **retained on the :class:`Built` object but not constructed by
:func:`agno_spec_builder.build`**. The parent application reads it off the
validated root and is responsible for translating it into an
``agno.os.AgentOS`` instance and calling ``serve()`` with the matching server
kwargs. This mirrors how ``project`` and ``tests`` are handled: the document
owns the declaration, the application owns the execution.

Shape (YAML)::

    agentos:
      enabled: true
      a2a_interface: true
      agui_interface: true
      server:
        port: 8000
      db:
        kind: sqlite
        spec:
          db_file: agno.db

The ``server`` block mirrors the kwargs of
``agno.os.AgentOS.serve(app, host, port, workers, reload)`` so it can be
splatted directly into that call.

The ``db`` block mirrors :class:`ProviderConfig`'s shape (``kind`` + ``spec``)
and lets the YAML pick the AgentOS database backend without forcing the caller
to construct a ``BaseDb`` instance by hand. ``spec`` is a free-form dict whose
keys are forwarded to the chosen db class constructor; secret refs
(``$VAR``, ``${VAR}``) are expanded at build time via
:func:`agno_spec_builder.utils.expand_env`. When ``db`` is omitted,
:func:`build_agentos` falls back to ``runtime.db`` (the db injected into
:func:`build`), preserving the existing injection escape hatch.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Db backends AgentOS supports out of the box. ``in_memory`` is the default
# the spec-builder uses when nothing is injected; the others require the
# matching agno optional SDK (sqlalchemy for sqlite/postgres, etc.).
AgentOsDbKind = Literal["in_memory", "sqlite", "postgres"]


class AgentOsServerConfig(BaseModel):
    """uvicorn server options passed to :meth:`agno.os.AgentOS.serve`.

    Field names match the parameters of ``AgentOS.serve`` one-for-one so the
    resolved dict can be forwarded without translation.
    """

    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        default="localhost",
        description="Host to bind the AgentOS server to. Forwarded to ``AgentOS.serve(host=...)``.",
    )
    port: int = Field(
        default=7777,
        description="Port to bind the AgentOS server to. Agno's default is 7777.",
        ge=0,
        le=65535,
    )
    workers: int | None = Field(
        default=None,
        description=(
            "Number of uvicorn workers. ``None`` lets uvicorn pick its default. "
            "Forwarded to ``AgentOS.serve(workers=...)``."
        ),
    )
    reload: bool = Field(
        default=False,
        description="Enable uvicorn auto-reload for development. Forwarded to ``AgentOS.serve(reload=...)``.",
    )


class AgentOsDbConfig(BaseModel):
    """Declarative AgentOS database backend.

    Mirrors the ``kind`` + ``spec`` shape of :class:`ProviderConfig` so YAML
    authors can pick a db backend the same way they pick a model provider.
    ``spec`` is a free-form dict (``ConfigDict(extra="allow")``): any kwarg the
    chosen db class constructor accepts can be set here. Secret refs
    (``$VAR``, ``${VAR}``, ``${input:var}``) are expanded at build time.
    """

    model_config = ConfigDict(extra="forbid")

    kind: AgentOsDbKind = Field(
        description=(
            "Database backend for AgentOS. ``in_memory`` is ephemeral and "
            "useful for tests; ``sqlite`` and ``postgres`` persist sessions, "
            "memory, knowledge, and traces."
        ),
    )
    spec: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Constructor kwargs for the chosen db class "
            "(db_file, db_url, db_engine, table names, …). "
            "Secret refs ($VAR, ${VAR}, ${input:var}) are expanded at build time."
        ),
    )


class AgentOsConfig(BaseModel):
    """Declarative AgentOS runtime configuration.

    ``enabled`` gates whether the parent application should serve the built
    graph over AgentOS at all. When enabled, ``server`` carries the uvicorn
    kwargs that ``AgentOS.serve`` accepts, ``a2a_interface`` enables Agno's
    Agent-to-Agent protocol routes for every built resource,
    ``agui_interface`` enables Agent-User Interaction routes for built agents
    and teams, and ``db`` optionally picks the AgentOS database backend.

    AgentOS-level concerns that overlap with what :func:`build` already
    produces (agents, teams, workflows, knowledge) are intentionally not
    duplicated here — the parent application wires them into the
    ``AgentOS(...)`` constructor from the :class:`Built` object.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Whether the parent application should serve the built graph via "
            "``agno.os.AgentOS``. When ``False`` (the default), the ``server`` "
            "and ``db`` blocks are ignored."
        ),
    )
    id: str | None = Field(
        default=None,
        description=(
            "Optional stable AgentOS identifier. Environment references "
            "(``$VAR`` or ``${VAR}``) are expanded when AgentOS is constructed."
        ),
    )
    a2a_interface: bool = Field(
        default=False,
        description=(
            "Expose all built agents, teams, and workflows through Agno's "
            "Agent-to-Agent (A2A) interface. Requires the ``a2a-sdk`` package."
        ),
    )
    agui_interface: bool = Field(
        default=False,
        description=(
            "Expose all built agents and teams through Agno's Agent-User Interaction "
            "(AG-UI) interface. Workflows are not supported. Requires ``ag-ui-protocol``."
        ),
    )
    server: AgentOsServerConfig = Field(
        default_factory=AgentOsServerConfig,
        description="uvicorn server options forwarded to ``AgentOS.serve(**server)``.",
    )
    db: AgentOsDbConfig | None = Field(
        default=None,
        description=(
            "Optional AgentOS database backend. When omitted, "
            ":func:`build_agentos` falls back to ``runtime.db`` (the db "
            "injected into :func:`build`)."
        ),
    )
