"""Typed shape of the top-level YAML `mcp:` catalog."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class McpServerConfig(BaseModel):
    # Remote HTTP MCP is the default shape (`type: http`, `url`, `headers`).
    # stdio (`command` + `env`) remains for local dev only. Secrets in headers/env
    # use `${env.VAR}` or `${input:var}` → env today (e.g. github_mcp_pat →
    # GITHUB_MCP_PAT). DB-backed secrets are planned, not wired yet.
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str = Field(
        description=("Server name in the top-level `mcp:` catalog; referenced by an agent's `mcp:` list.")
    )
    type: Literal["http", "sse", "stdio"] | None = Field(
        default=None,
        description=("Cursor/IDE-style transport alias: 'http' -> streamable-http, or 'sse'/'stdio' directly."),
    )
    transport: Literal["stdio", "sse", "streamable-http"] | None = Field(
        default=None,
        description=("agno's native transport name. Inferred from `type`, or from `url`/`command` if omitted."),
    )
    url: str | None = Field(
        default=None,
        description="Server URL, required for sse/streamable-http transports.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "HTTP headers sent to the server. Secrets: use '${env.VAR}' or '${input:var}' (resolved from env)."
        ),
    )
    # stdio-only (legacy local servers, e.g. npx …)
    command: str | None = Field(
        default=None,
        description=("Shell command to launch a local stdio server (legacy/dev only, e.g. `npx ...`)."),
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables passed to the stdio `command` process.",
    )
    include_tools: list[str] | None = Field(
        default=None,
        description="If set, only these tool names from this server are exposed to agents.",
    )
    exclude_tools: list[str] | None = Field(
        default=None,
        description=("Tool names from this server to hide from agents (keeps per-turn schemas small)."),
    )

    @model_validator(mode="after")
    def normalize(self) -> Self:
        if self.type == "http":
            self.transport = "streamable-http"
        elif self.type in ("sse", "stdio"):
            self.transport = self.type
        if self.transport is None:
            self.transport = "streamable-http" if self.url else "stdio" if self.command else None
        if not self.transport:
            raise ValueError(f"mcp server {self.name!r}: need `url` + `type: http` or `command` (stdio)")
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"mcp server {self.name!r}: stdio transport needs `command`")
        if self.transport in ("sse", "streamable-http") and not self.url:
            raise ValueError(f"mcp server {self.name!r}: {self.transport} transport needs `url`")
        return self
