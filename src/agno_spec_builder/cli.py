"""Command-line entry point: build a graph from a YAML spec and serve it via AgentOS.

Usage::

    agno-spec-builder -f path/to/agent.yml
    python -m agno_spec_builder.cli -f path/to/agent.yml

The spec must enable ``agentos.enabled: true``; otherwise there is nothing to
serve and the command exits with an error. Server kwargs (host/port/workers/reload)
come from the spec's ``agentos.server`` block — CLI flags override them.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from agno_spec_builder import build, build_agentos


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agno-spec-builder",
        description="Build an Agno runtime graph from a YAML spec and serve it via AgentOS.",
    )
    parser.add_argument(
        "-f",
        "--file",
        dest="file",
        required=True,
        type=Path,
        help="Path to the YAML spec file.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Override agentos.server.host (default: localhost).",
    )
    parser.add_argument(
        "--port",
        default=None,
        type=int,
        help="Override agentos.server.port (default: 7777).",
    )
    parser.add_argument(
        "--workers",
        default=None,
        type=int,
        help="Override agentos.server.workers (uvicorn worker count).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (dev mode). Overrides agentos.server.reload.",
    )
    return parser.parse_args(argv)


def _server_kwargs(runtime: Any, args: argparse.Namespace) -> dict[str, Any]:
    """Merge the spec's agentos.server block with CLI overrides; CLI flags win."""
    server = dict(runtime.agentos.server.model_dump(exclude_none=True))
    if args.host is not None:
        server["host"] = args.host
    if args.port is not None:
        server["port"] = args.port
    if args.workers is not None:
        server["workers"] = args.workers
    if args.reload:
        server["reload"] = True
    return server


async def _prepare(spec_path: Path, args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    """Build the runtime + AgentOS, returning (agent_os, server_kwargs).

    AgentOS.serve() owns its own uvicorn event loop, so it must run *after* the
    async build coroutines have completed — hence we split prepare from serve.
    """
    runtime = await build(spec_path)
    if not runtime.agentos.enabled:
        print(
            "agentos is disabled in the spec; set `agentos.enabled: true` to serve.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    server_kwargs = _server_kwargs(runtime, args)
    agent_os = await build_agentos(runtime)
    if agent_os is None:  # defensive — enabled implies a non-None return
        print("build_agentos() returned None despite agentos.enabled=true.", file=sys.stderr)
        raise SystemExit(3)
    return agent_os, server_kwargs


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if not args.file.exists():
        print(f"spec file not found: {args.file}", file=sys.stderr)
        raise SystemExit(1)
    agent_os, server_kwargs = asyncio.run(_prepare(args.file, args))
    print(f"starting AgentOS: {server_kwargs.get('host', 'localhost')}:{server_kwargs.get('port', 7777)}")
    agent_os.serve(app=agent_os.get_app(), **server_kwargs)


if __name__ == "__main__":
    main()
