import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from agno_spec_builder import build as async_build
from agno_spec_builder.builders.agents import MODEL_PROVIDERS


def build(*args, **kwargs):
    return asyncio.run(async_build(*args, **kwargs))


def background_spec() -> dict:
    return {
        "models": {"default": {"provider": "fake", "id": "offline"}},
        "agents": [
            {"name": "Background Agent", "model": {"id": "default"}, "background": True},
            {"name": "Foreground Agent", "model": {"id": "default"}},
        ],
        "teams": [
            {"name": "Background Team", "members": ["background-agent"], "background": True},
        ],
        "workflows": [
            {
                "name": "Background Workflow",
                "background": True,
                "steps": [{"name": "work", "run": "agent.background-agent"}],
            }
        ],
    }


class BackgroundExecutionTests(unittest.TestCase):
    def setUp(self):
        self.previous_fake = MODEL_PROVIDERS.get("fake")
        MODEL_PROVIDERS["fake"] = "tests.fake_provider:FakeModel"

    def tearDown(self):
        if self.previous_fake is None:
            MODEL_PROVIDERS.pop("fake", None)
        else:
            MODEL_PROVIDERS["fake"] = self.previous_fake

    def test_build_records_background_defaults_for_all_resource_kinds(self):
        runtime = build(background_spec())

        self.assertEqual(
            runtime.background_defaults,
            {
                "agent.background-agent": True,
                "agent.foreground-agent": False,
                "team.background-team": True,
                "workflow.background-workflow": True,
            },
        )
        self.assertIsNotNone(runtime.agents["background-agent"].db)
        self.assertIsNotNone(runtime.teams["background-team"].db)
        self.assertIsNotNone(runtime.workflows["background-workflow"].db)

    def test_arun_applies_defaults_to_agents_teams_and_workflows(self):
        runtime = build(background_spec())

        async def exercise():
            for ref in ("agent.background-agent", "team.background-team", "workflow.background-workflow"):
                resource = runtime._target(ref)
                mocked = AsyncMock(return_value=ref)
                with patch.object(resource, "arun", mocked):
                    self.assertEqual(await runtime.arun(ref, "research this"), ref)
                mocked.assert_awaited_once_with("research this", background=True)

        asyncio.run(exercise())

    def test_arun_returns_plain_resource_streams_without_awaiting_them(self):
        runtime = build(background_spec())

        async def exercise():
            cases = (
                ("agent.background-agent", False),
                ("team.background-team", True),
                ("workflow.background-workflow", True),
            )
            for ref, expected_background in cases:
                resource = runtime._target(ref)
                calls = []

                async def stream_run(input, _calls=calls, _ref=ref, **kwargs):
                    _calls.append((input, kwargs))
                    yield _ref

                kwargs = {"stream": True, "user_id": "user-1"}
                if not expected_background:
                    kwargs["background"] = False
                with patch.object(resource, "arun", stream_run):
                    events = await runtime.arun(ref, "research this", **kwargs)
                    self.assertEqual([event async for event in events], [ref])
                self.assertEqual(
                    calls,
                    [("research this", {"background": expected_background, "stream": True, "user_id": "user-1"})],
                )

        asyncio.run(exercise())

    def test_arun_forwards_a_configured_stream_default(self):
        runtime = build(
            {
                "models": {"default": {"provider": "fake", "id": "offline"}},
                "agents": [{"name": "Worker", "model": {"id": "default"}}],
                "workflows": [
                    {
                        "name": "Streaming Workflow",
                        "background": True,
                        "stream": True,
                        "steps": [{"name": "work", "run": "agent.worker"}],
                    }
                ],
            }
        )
        workflow = runtime.workflows["streaming-workflow"]
        calls = []

        async def stream_run(input, **kwargs):
            calls.append((input, kwargs))
            yield "event"

        async def exercise():
            with patch.object(workflow, "arun", stream_run):
                events = await runtime.arun("workflow.streaming-workflow", "research this")
                self.assertEqual([event async for event in events], ["event"])

        asyncio.run(exercise())
        self.assertEqual(calls, [("research this", {"background": True, "stream": True})])

    def test_aget_run_output_delegates_to_the_selected_resource(self):
        runtime = build(background_spec())
        workflow = runtime.workflows["background-workflow"]
        mocked = AsyncMock(return_value="completed output")

        async def exercise():
            with patch.object(workflow, "aget_run_output", mocked):
                result = await runtime.aget_run_output(
                    "workflow.background-workflow",
                    "run-1",
                    session_id="session-1",
                    user_id="user-1",
                )
            self.assertEqual(result, "completed output")

        asyncio.run(exercise())
        mocked.assert_awaited_once_with(run_id="run-1", session_id="session-1", user_id="user-1")

    def test_runtime_rejects_malformed_and_unknown_targets(self):
        runtime = build(background_spec())
        with self.assertRaisesRegex(ValueError, "target must be"):
            runtime._target("background-agent")
        with self.assertRaisesRegex(ValueError, "unknown agent target"):
            runtime._target("agent.missing")


if __name__ == "__main__":
    unittest.main()
