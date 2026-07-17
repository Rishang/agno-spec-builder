import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from agno.db.in_memory import InMemoryDb
from pydantic import ValidationError

from agno_spec_builder import BaseSchema, build
from agno_spec_builder.builders.agents import MODEL_PROVIDERS
from agno_spec_builder.builders.schemas import SchemaBuilder
from agno_spec_builder.imports import resolve_symbol
from agno_spec_builder.schemas import AgentConfig, ProviderConfig
from agno_spec_builder.schemas.model import ModelConfig


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
                spec={"api_key": "$SPEC_BUILDER_TEST_KEY"},
            )
            self.assertEqual(provider.resolved_spec(), {"api_key": "secret"})
        finally:
            os.environ.pop("SPEC_BUILDER_TEST_KEY", None)

    def test_aggregate_schema_defaults_all_catalogs(self):
        spec = BaseSchema(agents=[])
        self.assertEqual(spec.models, {})
        self.assertEqual(spec.mcp, [])
        self.assertEqual(spec.workflows, [])

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


if __name__ == "__main__":
    unittest.main()
