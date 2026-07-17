"""YAML `mcp:` catalog → MCPTools, connected fresh on every call.

Streamable-http, SSE, and stdio MCP clients bind anyio cancel scopes to the task
that opened them, so a connection must be opened/used/closed in one task —
`McpToolkit.connect` does exactly that per call. This used to be expensive
enough to warrant an in-process warm-connection pool (`_WarmMcp`/`McpRunner`
owner tasks); that's now agentgateway's job (`task gateway`) — warm upstream
connections behind a local `/mcp`, so a fresh connect here is a cheap localhost hop.
Plain agents (no `mcp:` list) skip all of it. Trim per-turn tool schemas with
per-agent `include_tools`/`exclude_tools` (discover names via
`GET /mcp/{name}/tools`).
"""

import copy
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, cast

from agno.agent import Agent
from agno.team import Team
from agno.tools.mcp import MCPTools
from agno.tools.mcp.params import SSEClientParams, StreamableHTTPClientParams
from agno.workflow import Workflow

from agno_spec_builder.mcp.schema import McpServerConfig
from agno_spec_builder.utils import expand_env, resolve

# extra="allow" on McpServerConfig passes through model_dump(exclude=_WIRED).
_WIRED = {"name", "type", "transport", "command", "env", "url", "headers",
          "include_tools", "exclude_tools"}  # fmt: skip


class McpToolkit:
    """Builds and connects MCPTools from YAML server configs."""

    @staticmethod
    def build(names: list[str], servers: dict[str, McpServerConfig]) -> list[MCPTools]:
        """Construct (unconnected) MCPTools for the named servers."""
        tools: list[MCPTools] = []
        for cfg in resolve(names, servers):
            kw: dict[str, Any] = cfg.model_dump(  # extra="allow" passthrough (exclude wired)
                exclude=_WIRED, exclude_none=True, exclude_defaults=True
            )
            kw |= dict(transport=cfg.transport, include_tools=cfg.include_tools,
                       exclude_tools=cfg.exclude_tools)  # fmt: skip
            if cfg.transport == "stdio":
                kw.setdefault("timeout_seconds", 60)
                kw |= dict(command=cfg.command, env=expand_env(cfg.env) or None)
            else:
                url = kw["url"] = cast(str, cfg.url)  # normalize() guarantees url for http/sse
                params = SSEClientParams if cfg.transport == "sse" else StreamableHTTPClientParams
                kw["server_params"] = params(url=url, headers=expand_env(cfg.headers) or None)
            tools.append(MCPTools(**kw))
        return tools

    @classmethod
    @asynccontextmanager
    async def connect(cls, names: list[str], servers: dict[str, McpServerConfig]) -> AsyncIterator[list[MCPTools]]:
        """Open the named servers, yield live toolkits, close on exit — all in one task."""
        async with AsyncExitStack() as stack:
            tools = cls.build(names, servers)
            for tool in tools:
                await stack.enter_async_context(tool)
            yield tools

    @classmethod
    async def probe(cls, cfg: McpServerConfig) -> list[dict[str, str]]:
        """Connect one server and list its tools (for the /mcp routes)."""
        async with cls.connect([cfg.name], {cfg.name: cfg}) as (toolkit,):
            return [{"name": fn.name, "description": fn.description or ""} for fn in toolkit.functions.values()]

    @staticmethod
    def public(cfg: McpServerConfig) -> dict[str, Any]:
        """JSON-safe view of a server config (no secrets)."""
        kind = cfg.type or ("http" if cfg.transport == "streamable-http" else cfg.transport)
        return {
            "name": cfg.name,
            "type": kind,
            "url": cfg.url,
            "include_tools": cfg.include_tools,
            "exclude_tools": cfg.exclude_tools,
        }


class McpRunner:
    """Runs agents with MCP tools from one built graph's server catalog."""

    def __init__(self, servers: dict[str, McpServerConfig] | None = None) -> None:
        self.servers = servers or {}

    @staticmethod
    def names(agent: Agent) -> list[str]:
        names = (agent.metadata or {}).get("mcp")  # set by build_agent() from YAML `mcp:`
        return names if isinstance(names, list) else []

    @staticmethod
    def needs(agent: Agent) -> bool:
        return bool(McpRunner.names(agent))

    @staticmethod
    def _run_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        # Agno's overloads want stream=True as a literal arg, not via **kwargs.
        return {k: v for k, v in kwargs.items() if k != "stream"}

    def _with_tools(self, agent: Agent, tools: list[MCPTools]) -> Agent:
        run = copy.copy(agent)  # shallow: only tools differ; db/session/model stay shared
        base = list(agent.tools) if isinstance(agent.tools, list) else []
        run.tools = cast(Any, [*base, *tools])
        return run

    async def invoke(self, agent: Agent, input: str, **kwargs: Any):
        opts = self._run_kwargs(kwargs)
        if not self.needs(agent):
            return await agent.arun(input, **opts)
        async with McpToolkit.connect(self.names(agent), self.servers) as tools:
            return await self._with_tools(agent, tools).arun(input, **opts)

    async def stream(self, agent: Agent, input: str, **kwargs: Any):
        opts = self._run_kwargs(kwargs)
        if not self.needs(agent):
            async for ev in agent.arun(input, stream=True, **opts):
                yield ev
            return
        async with McpToolkit.connect(self.names(agent), self.servers) as tools:
            async for ev in self._with_tools(agent, tools).arun(input, stream=True, **opts):
                yield ev

    async def arun_target(self, obj: Agent | Team | Workflow, inp: str, **kwargs) -> Any:
        # Workflow (nested-workflow steps) has no MCP tool injection of its own —
        # falls straight to obj.arun(); its sub-steps resolve their own MCP needs.
        if isinstance(obj, Agent) and self.needs(obj):
            return (await self.invoke(obj, inp, **kwargs)).content
        return (await obj.arun(inp, **kwargs)).content

    async def astream_target(self, obj: Agent | Team | Workflow, inp: str, **kwargs: Any):
        """Streaming twin of arun_target: yield a child agent/team/workflow's run
        events (tool calls, skill-load calls, reasoning, content deltas) instead of
        collapsing the run to its final .content. Lets a workflow custom executor
        surface those events on the wire — arun_target() swallows them all."""
        if isinstance(obj, Agent):
            async for ev in self.stream(obj, inp, stream_events=True, **kwargs):
                yield ev
        else:
            async for ev in obj.arun(inp, stream=True, stream_events=True, **kwargs):
                yield ev
