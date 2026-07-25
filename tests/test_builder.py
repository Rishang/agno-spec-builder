import asyncio
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, call, patch

from agno.db.in_memory import InMemoryDb
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import agno_spec_builder.tools as tools_module
from agno_spec_builder import BaseSchema
from agno_spec_builder import build as async_build
from agno_spec_builder import build_agentos as async_build_agentos
from agno_spec_builder.builders.agents import MODEL_PROVIDERS
from agno_spec_builder.builders.schemas import SchemaBuilder
from agno_spec_builder.imports import resolve_symbol
from agno_spec_builder.schemas import AgentConfig, ProviderConfig
from agno_spec_builder.schemas.model import ModelConfig
from agno_spec_builder.tools import TOOLSET_REGISTRY
from agno_spec_builder.tools.a2a import A2ATools
from agno_spec_builder.webhooks import attach_webhook_routes

try:
    importlib.import_module("agno.os.interfaces.agui")
except ImportError:
    _AGUI_AVAILABLE = False
else:
    _AGUI_AVAILABLE = True


def build(*args, **kwargs):
    return asyncio.run(async_build(*args, **kwargs))


def build_agentos(*args, **kwargs):
    return asyncio.run(async_build_agentos(*args, **kwargs))


def webhook_spec() -> dict[str, Any]:
    return {
        "agentos": {"enabled": True},
        "models": {"default": {"provider": "fake", "id": "offline"}},
        "agents": [{"name": "CPU Agent", "model": {"id": "default"}}],
        "webhooks": [
            {
                "name": "grafana-alerts",
                "path": "grafana-alerts",
                "secret": "test-secret",
                "secret_header": "X-Grafana-Token",
                "triggers": [
                    {
                        "kind": "agent",
                        "name": "cpu-agent",
                        "match": {"field": "alerts[0].labels.alertname", "value": "CPUHighUsage"},
                        "prompt": "Analyze this alert:\n{payload}",
                    }
                ],
            }
        ],
    }


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.previous_fake = MODEL_PROVIDERS.get("fake")
        MODEL_PROVIDERS["fake"] = "tests.fake_provider:FakeModel"

    def tearDown(self):
        if self.previous_fake is None:
            MODEL_PROVIDERS.pop("fake", None)
        else:
            MODEL_PROVIDERS["fake"] = self.previous_fake

    def test_builds_complete_graph_with_owned_runtime_state(self):
        runtime = build(
            {
                "project": "builder-tests",
                "models": {"default": {"provider": "fake", "id": "offline"}},
                "vectordb": [{"name": "primary", "provider": "qdrant", "url": "http://localhost"}],
                "tests": [{"name": "smoke", "input": "hello"}],
                "skills": [
                    {
                        "name": "concise",
                        "content": "---\nname: concise\ndescription: Be concise\n---\nUse short answers.",
                    }
                ],
                "agents": [
                    {
                        "name": "Research Agent",
                        "model": {"id": "default"},
                        "skills": ["concise"],
                    }
                ],
                "teams": [{"name": "Research Team", "members": ["research-agent"]}],
                "workflows": [
                    {
                        "name": "Research Flow",
                        "steps": [{"name": "research", "run": "agent.research-agent"}],
                    }
                ],
                "mcp": [{"name": "local", "type": "stdio", "command": "echo ready"}],
                "schedules": [
                    {
                        "name": "daily",
                        "cron": "0 9 * * *",
                        "kind": "workflow",
                        "slug": "research-flow",
                    }
                ],
            }
        )

        self.assertIsInstance(runtime.db, InMemoryDb)
        self.assertEqual(set(runtime.agents), {"research-agent"})
        self.assertEqual(set(runtime.teams), {"research-team"})
        self.assertEqual(set(runtime.workflows), {"research-flow"})
        self.assertEqual(set(runtime.skills), {"concise"})
        self.assertEqual(set(runtime.mcp_servers), {"local"})
        self.assertIs(runtime.mcp_runner.servers, runtime.mcp_servers)
        self.assertEqual(runtime.schedules["daily"].endpoint, "/workflow/research-flow/run")
        self.assertEqual(runtime.project, "builder-tests")
        self.assertEqual(runtime.vector_dbs["primary"]["provider"], "qdrant")
        self.assertEqual(runtime.tests[0]["name"], "smoke")

    def test_webhook_catalog_validates_agent_references_and_templates(self):
        runtime = build(webhook_spec())
        self.assertEqual(set(runtime.webhooks), {"grafana-alerts"})

        invalid_agent = webhook_spec()
        invalid_agent["webhooks"][0]["triggers"][0]["name"] = "unknown"
        with self.assertRaisesRegex(ValidationError, "unknown agent"):
            BaseSchema.model_validate(invalid_agent)

        invalid_template = webhook_spec()
        invalid_template["webhooks"][0]["triggers"][0]["prompt"] = "Alert for {unknown}"
        with self.assertRaisesRegex(ValidationError, "support only"):
            BaseSchema.model_validate(invalid_template)

    def test_audio_model_and_toolsets_are_wired_into_an_agent(self):
        class FakeToolkit:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.name = "fake-toolkit"
                self.functions = {}

        with patch.object(tools_module, "resolve_symbol", return_value=FakeToolkit) as resolve_toolset:
            runtime = build(
                {
                    "models": {
                        "audio": {
                            "provider": "openai",
                            "id": "gpt-audio",
                            "modalities": ["text", "audio"],
                            "audio": {"voice": "sage", "format": "wav"},
                        },
                        "podcast": {"provider": "openai-responses", "id": "gpt-5.2"},
                    },
                    "toolsets": [
                        {
                            "name": "transcription",
                            "type": "openai",
                            "init": {
                                "transcription_model": "gpt-4o-transcribe",
                                "enable_image_generation": False,
                                "enable_speech_generation": False,
                            },
                        },
                        {
                            "name": "podcast-voice",
                            "type": "elevenlabs",
                            "init": {"voice_id": "voice-id", "model_id": "eleven_multilingual_v2"},
                        },
                        {"name": "web-research", "type": "firecrawl"},
                    ],
                    "agents": [
                        {
                            "name": "Audio Agent",
                            "model": {"id": "audio"},
                            "tools": ["transcription", "podcast-voice", "web-research"],
                        },
                        {"name": "Podcast Agent", "model": {"id": "podcast"}},
                    ],
                }
            )

        model = runtime.agents["audio-agent"].model
        self.assertEqual(model.modalities, ["text", "audio"])
        self.assertEqual(model.audio, {"voice": "sage", "format": "wav"})
        self.assertEqual(runtime.agents["podcast-agent"].model.id, "gpt-5.2")
        self.assertEqual(
            [tool.kwargs for tool in runtime.agents["audio-agent"].tools],
            [
                {
                    "transcription_model": "gpt-4o-transcribe",
                    "enable_image_generation": False,
                    "enable_speech_generation": False,
                },
                {"voice_id": "voice-id", "model_id": "eleven_multilingual_v2"},
                {},
            ],
        )
        self.assertEqual(
            [call.args[0] for call in resolve_toolset.call_args_list],
            [
                "agno.tools.openai:OpenAITools",
                "agno.tools.eleven_labs:ElevenLabsTools",
                "agno.tools.firecrawl:FirecrawlTools",
            ],
        )

    def test_toolset_provider_ref_merges_connection_kwargs_under_init(self):
        captured: dict[str, Any] = {}
        toolkit = MagicMock()

        def fake_factory(name, **init):
            captured.update(init)
            return toolkit

        with patch.dict(TOOLSET_REGISTRY, {"conn-tool": fake_factory}):
            runtime = build(
                {
                    "providers": [
                        {
                            "name": "openrouter",
                            "kind": "models",
                            "spec": {"base_url": "https://openrouter.ai/api/v1", "api_key": "secret"},
                        }
                    ],
                    "toolsets": [
                        {
                            "name": "tts",
                            "type": "conn-tool",
                            "provider": "openrouter",
                            "init": {"text_to_speech_model": "kokoro", "api_key": "override-wins"},
                        }
                    ],
                }
            )

        self.assertEqual(
            captured,
            {
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "override-wins",
                "text_to_speech_model": "kokoro",
            },
        )
        self.assertIs(runtime.toolsets["tts"], toolkit)

    def test_a2a_toolset_is_available_to_declaring_agent(self):
        runtime = build(
            {
                "models": {"default": {"provider": "fake", "id": "offline"}},
                "toolsets": [
                    {
                        "name": "research-agent",
                        "type": "a2a",
                        "url": "http://localhost:8080/a2a",
                        "headers": {"X-Tenant": "acme"},
                    }
                ],
                "agents": [
                    {
                        "name": "Research Coordinator",
                        "model": {"id": "default"},
                        "tools": ["research-agent"],
                    }
                ],
            }
        )

        self.assertEqual(runtime.toolsets["research-agent"].name, "research-agent")
        self.assertIn(runtime.toolsets["research-agent"], runtime.agents["research-coordinator"].tools)

    def test_TOOLSET_REGISTRY_allow_application_extensions(self):
        previous = TOOLSET_REGISTRY.get("partner-a2a")
        TOOLSET_REGISTRY["partner-a2a"] = A2ATools
        try:
            runtime = build(
                {
                    "models": {"default": {"provider": "fake", "id": "offline"}},
                    "toolsets": [
                        {
                            "name": "partner-agent",
                            "type": "partner-a2a",
                            "init": {"url": "http://partner.example/a2a", "headers": {"X-Tenant": "acme"}},
                        }
                    ],
                    "agents": [
                        {
                            "name": "Coordinator",
                            "model": {"id": "default"},
                            "tools": ["partner-agent"],
                        }
                    ],
                }
            )
        finally:
            if previous is None:
                TOOLSET_REGISTRY.pop("partner-a2a", None)
            else:
                TOOLSET_REGISTRY["partner-a2a"] = previous

        self.assertEqual(runtime.toolsets["partner-agent"].url, "http://partner.example/a2a")

    def test_mcp_runner_result_helpers_override_resource_stream_defaults(self):
        runtime = build(
            {
                "models": {"default": {"provider": "fake", "id": "offline"}},
                "agents": [{"name": "Streaming Agent", "model": {"id": "default"}, "stream": True}],
            }
        )
        agent = runtime.agents["streaming-agent"]
        mocked = AsyncMock(return_value=SimpleNamespace(content="result"))

        async def exercise():
            with patch.object(agent, "arun", mocked):
                self.assertEqual((await runtime.mcp_runner.invoke(agent, "hello")).content, "result")
                self.assertEqual(await runtime.mcp_runner.arun_target(agent, "hello"), "result")

        asyncio.run(exercise())
        self.assertEqual(mocked.await_args_list, [call("hello", stream=False), call("hello", stream=False)])

    def test_webhook_route_authenticates_matches_and_invokes_agent(self):
        runtime = build(webhook_spec())
        runtime.mcp_runner.arun_target = AsyncMock(return_value="CPU remediation")  # type: ignore[method-assign]
        app = attach_webhook_routes(FastAPI(), runtime)
        client = TestClient(app)

        unauthorized = client.post("/webhooks/grafana-alerts", json={})
        self.assertEqual(unauthorized.status_code, 401)

        response = client.post(
            "/webhooks/grafana-alerts",
            headers={"X-Grafana-Token": "test-secret"},
            json={"alerts": [{"labels": {"alertname": "CPUHighUsage"}}]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["analysis"], "CPU remediation")
        runtime.mcp_runner.arun_target.assert_awaited_once()

        no_match = client.post(
            "/webhooks/grafana-alerts",
            headers={"X-Grafana-Token": "test-secret"},
            json={"alerts": [{"labels": {"alertname": "MemoryHighUsage"}}]},
        )
        self.assertEqual(no_match.json(), {"ok": True, "matched": 0, "results": []})

    def test_webhook_routes_reuse_caller_fastapi_app(self):
        runtime = build(webhook_spec())
        app = FastAPI()
        with patch("agno.os.AgentOS") as mock_agent_os:
            build_agentos(runtime, base_app=app)
        self.assertIs(mock_agent_os.call_args.kwargs["base_app"], app)
        self.assertIn("/webhooks/grafana-alerts", {getattr(route, "path", None) for route in app.routes})

    def test_schema_builder_supports_nested_and_optional_types(self):
        schemas = SchemaBuilder(
            {
                "Address": {"fields": {"city": "str"}},
                "Person": {
                    "fields": {
                        "name": "str",
                        "email": "email",
                        "address": "Address",
                        "tags": "list[str]?",
                    }
                },
            }
        )
        person = schemas.output_schema("Person")(name="Ada", email="ada@example.com", address={"city": "London"})
        self.assertEqual(cast(Any, person).address.city, "London")
        self.assertEqual(str(cast(Any, person).email), "ada@example.com")
        self.assertIsNone(cast(Any, person).tags)

    def test_provider_secrets_expand_from_environment(self):
        os.environ["SPEC_BUILDER_TEST_KEY"] = "secret"
        try:
            provider = ProviderConfig(
                name="custom",
                kind="models",
                spec={"api_key": "${env.SPEC_BUILDER_TEST_KEY}"},
            )
            self.assertEqual(provider.resolved_spec(), {"api_key": "secret"})
            legacy = ProviderConfig(name="legacy", kind="models", spec={"api_key": "$SPEC_BUILDER_TEST_KEY"})
            self.assertEqual(legacy.resolved_spec(), {"api_key": "$SPEC_BUILDER_TEST_KEY"})
        finally:
            os.environ.pop("SPEC_BUILDER_TEST_KEY", None)

    def test_aggregate_schema_defaults_all_catalogs(self):
        spec = BaseSchema(agents=[])
        self.assertEqual(spec.models, {})
        self.assertEqual(spec.mcp, [])
        self.assertEqual(spec.workflows, [])

    @patch("agno.os.AgentOS")
    def test_build_agentos_forwards_a2a_interface_configuration(self, mock_agent_os):
        disabled = build({"agentos": {"enabled": True}})
        build_agentos(disabled)
        self.assertFalse(mock_agent_os.call_args.kwargs["a2a_interface"])

        enabled = build({"agentos": {"enabled": True, "a2a_interface": True}})
        build_agentos(enabled)
        self.assertTrue(mock_agent_os.call_args.kwargs["a2a_interface"])

    @unittest.skipUnless(_AGUI_AVAILABLE, "ag-ui optional dependency is not installed")
    @patch("agno.os.AgentOS")
    @patch("agno.os.interfaces.agui.AGUI")
    def test_build_agentos_generates_agui_interfaces(self, mock_agui, mock_agent_os):
        disabled = build({"agentos": {"enabled": True}})
        build_agentos(disabled)
        self.assertNotIn("interfaces", mock_agent_os.call_args.kwargs)

        enabled = build(
            {
                "agentos": {"enabled": True, "agui_interface": True},
                "models": {"default": {"provider": "fake", "id": "offline"}},
                "agents": [{"name": "Researcher", "model": {"id": "default"}}],
                "teams": [{"name": "Research Team", "members": ["researcher"]}],
            }
        )
        custom_interface = object()
        build_agentos(enabled, interfaces=[custom_interface])

        self.assertEqual(
            mock_agui.call_args_list,
            [
                call(agent=enabled.agents["researcher"], prefix="/agui/agents/researcher"),
                call(team=enabled.teams["research-team"], prefix="/agui/teams/research-team"),
            ],
        )
        self.assertEqual(
            mock_agent_os.call_args.kwargs["interfaces"],
            [custom_interface, mock_agui.return_value, mock_agui.return_value],
        )

    def test_load_source_supports_all_documented_input_forms(self):
        validated = BaseSchema(project="validated")
        self.assertEqual(build(validated).project, "validated")
        self.assertEqual(build({"project": "mapping"}).project, "mapping")
        self.assertEqual(build('{"project": "inline-json"}').project, "inline-json")
        self.assertEqual(build("project: inline-yaml").project, "inline-yaml")

        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "config.JSON"
            json_path.write_text('{"project": "json-file"}', encoding="utf-8")
            self.assertEqual(build(str(json_path)).project, "json-file")

            yaml_path = Path(directory) / "config.yml"
            yaml_path.write_text("project: yaml-path\n", encoding="utf-8")
            self.assertEqual(build(yaml_path).project, "yaml-path")

    def test_yaml_path_is_validated_by_authoritative_root_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.yml"
            path.write_text("agents: []\nagnts: []\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "agnts"):
                build(path)

    def test_root_schema_validates_named_catalogs_and_duplicate_slugs(self):
        with self.assertRaisesRegex(ValidationError, "needs a non-empty `name`"):
            BaseSchema(models=[{"provider": "fake", "id": "offline"}])
        with self.assertRaisesRegex(ValidationError, "duplicate agents names"):
            BaseSchema(
                agents=[
                    AgentConfig(name="One", slug="shared", model=ModelConfig(provider="fake", id="one")),
                    AgentConfig(name="Two", slug="shared", model=ModelConfig(provider="fake", id="two")),
                ]
            )

    def test_lazy_imports_are_cached(self):
        resolve_symbol.cache_clear()
        first = resolve_symbol("collections:Counter")
        second = resolve_symbol("collections:Counter")
        self.assertIs(first, second)
        self.assertEqual(resolve_symbol.cache_info().hits, 1)
        self.assertEqual(resolve_symbol.cache_info().misses, 1)

    @patch("agno_spec_builder.tools.a2a.A2AClient")
    def test_a2a_tool_sends_messages_with_configured_headers(self, mock_client):
        mock_client.return_value.send_message = AsyncMock(return_value=SimpleNamespace(content="remote result"))
        tool = A2ATools(
            "http://localhost:8080/a2a",
            name="research_agent",
            headers={"X-Tenant": "acme"},
        )

        result = asyncio.run(tool.ask("Research this", user_id="tenant-user"))

        self.assertEqual(result, "remote result")
        mock_client.assert_called_once_with("http://localhost:8080/a2a", timeout=30, protocol="rest")
        mock_client.return_value.send_message.assert_awaited_once_with(
            "Research this",
            context_id=None,
            user_id="tenant-user",
            metadata=None,
            headers={"X-Tenant": "acme"},
        )

    @patch("agno_spec_builder.builders.knowledge.resolve_symbol")
    def test_build_knowledge_constructs_lancedb_vector_provider(self, mock_resolve_symbol):
        from agno.vectordb.distance import Distance
        from agno.vectordb.search import SearchType

        from agno_spec_builder.builders.knowledge import build_knowledge
        from agno_spec_builder.schemas.knowledge import KnowledgeConfig

        mock_lancedb_cls = MagicMock()
        mock_resolve_symbol.return_value = mock_lancedb_cls

        cfg = KnowledgeConfig(
            name="Docs Knowledge",
            description="Documentation knowledge base",
            max_results=5,
            vector_db={"provider": "lancedb", "search_type": "hybrid", "distance": "cosine"},
        )
        providers = {
            "lancedb": ProviderConfig(
                name="lancedb",
                kind="vectordb",
                spec={"uri": "/tmp/lancedb_test", "api_key": "secret-key"},
            )
        }

        knowledge = build_knowledge(cfg, providers=providers, namespace="acme")

        self.assertEqual(knowledge.name, "Docs Knowledge")
        self.assertEqual(knowledge.description, "Documentation knowledge base")
        self.assertEqual(knowledge.max_results, 5)
        mock_lancedb_cls.assert_called_once_with(
            uri="/tmp/lancedb_test",
            api_key="secret-key",
            table_name="acme__docs-knowledge",
            search_type=SearchType.hybrid,
            distance=Distance.cosine,
        )


if __name__ == "__main__":
    unittest.main()
