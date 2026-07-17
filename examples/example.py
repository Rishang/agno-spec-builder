"""Single-file agno-spec-builder example.

Run validation only (no provider SDK or network required):
    uv run python examples/example.py

Build the runtime graph (requires ``openai==2.44.0`` and OPENAI_API_KEY):
    RUN_BUILD=1 uv run python examples/example.py
"""

import os

from agno_spec_builder import BaseSchema, build

# One plain dictionary is the complete source of truth.
SPEC = {
    "project": "support-demo",
    "providers": [
        {
            "name": "openai",
            "kind": "models",
            "spec": {"api_key": "$OPENAI_API_KEY"},
        }
    ],
    "models": [
        {
            "name": "default",
            "provider": "openai",
            "id": "gpt-4o-mini",
        }
    ],
    "vectordb": [
        {
            "name": "primary",
            "provider": "qdrant",
            "url": "http://localhost:6333",
        }
    ],
    "skills": [
        {
            "name": "support-style",
            "content": """---
name: support-style
description: Keep support answers practical and empathetic.
---
Acknowledge the issue, provide numbered steps, and end with one clear next action.
""",
        }
    ],
    "schemas": {
        "SupportReply": {
            "fields": {
                "summary": {"type": "str", "description": "One-sentence resolution."},
                "steps": "list[str]",
                "escalated": "bool",
                "ticket_id": "str?",
            }
        }
    },
    "mcp": [
        {
            "name": "local-support",
            "type": "stdio",
            "command": "python ./support_mcp_server.py",
            "include_tools": ["lookup_ticket"],
        }
    ],
    "agents": [
        {
            "name": "Support Specialist",
            "slug": "support-specialist",
            "model": {"id": "default"},
            "instructions": "Diagnose the request and return a structured support response.",
            "skills": ["support-style"],
            "tools": ["calculator"],
            "mcp": ["local-support"],
            "output_schema": "SupportReply",
        }
    ],
    "teams": [
        {
            "name": "Support Team",
            "slug": "support-team",
            "model": {"id": "default"},
            "members": ["support-specialist"],
            "mode": "coordinate",
        }
    ],
    "workflows": [
        {
            "name": "Resolve Ticket",
            "slug": "resolve-ticket",
            "steps": [{"name": "diagnose", "run": "agent.support-specialist"}],
        }
    ],
    "schedules": [
        {
            "name": "daily-support-summary",
            "cron": "0 18 * * 1-5",
            "kind": "workflow",
            "slug": "resolve-ticket",
            "payload": {"content": "Summarize unresolved support requests."},
        }
    ],
    "tests": [
        {
            "name": "password-reset",
            "target": "agent.support-specialist",
            "input": "I cannot reset my password.",
        }
    ],
}


def validate() -> BaseSchema:
    """Validate the complete root without constructing provider clients."""
    spec = BaseSchema.model_validate(SPEC)
    print("validated project:", spec.project)
    print("agent specs:", [agent.slug for agent in spec.agents])
    print("workflow specs:", [workflow.slug for workflow in spec.workflows])
    return spec


def build_runtime(spec: BaseSchema):
    """Build live Agno objects from the already-validated root."""
    runtime = build(spec)
    print("built agents:", list(runtime.agents))
    print("built teams:", list(runtime.teams))
    print("built workflows:", list(runtime.workflows))
    print("configured MCP servers:", list(runtime.mcp_servers))
    return runtime


if __name__ == "__main__":
    validated = validate()
    if os.getenv("RUN_BUILD") == "1":
        build_runtime(validated)
    else:
        print("Set RUN_BUILD=1 with OPENAI_API_KEY to construct the runtime graph.")

# Extension registries stay available from their owning modules:
# from agno_spec_builder.builders.agents import MODEL_PROVIDERS
# from agno_spec_builder.hooks import TOOL_HOOK_BUILDERS
# from agno_spec_builder.tools import TOOL_REGISTRY
