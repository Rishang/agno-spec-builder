"""Single-file agno-spec-builder example.

Build the runtime graph and start AgentOS:
    uv run python examples/example.py
"""

from pathlib import Path

import yaml
from dotenv import load_dotenv

from agno_spec_builder import BaseSchema, build, build_agentos

load_dotenv()
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
    runtime = build_runtime(validated)
    agent_os = build_agentos(runtime)
    if agent_os is None:
        raise RuntimeError("AgentOS is disabled; set agentos.enabled: true in the spec.")
    print("starting AgentOS:", runtime.agentos.server.host, runtime.agentos.server.port)
    agent_os.serve(app=agent_os.get_app(), **runtime.agentos.server.model_dump())

# Extension registries stay available from their owning modules:
# from agno_spec_builder.builders.agents import MODEL_PROVIDERS
# from agno_spec_builder.hooks import TOOL_HOOK_BUILDERS
# from agno_spec_builder.tools import TOOL_REGISTRY
