"""Single-file agno-spec-builder example.

Run validation only (no provider SDK or network required):
    uv run python examples/example.py

Build the runtime graph (requires ``openai==2.44.0`` and OPENAI_API_KEY):
    RUN_BUILD=1 uv run python examples/example.py
"""

import os
from pathlib import Path

import yaml

from agno_spec_builder import BaseSchema, build

SPEC_PATH = Path(__file__).parent / "example.yml"


def validate() -> BaseSchema:
    """Validate the complete root without constructing provider clients."""
    raw = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    spec = BaseSchema.model_validate(raw)
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
