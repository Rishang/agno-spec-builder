import asyncio
import unittest

from agno.workflow import Loop, Router, Step
from agno.workflow.types import StepInput
from pydantic import ValidationError

from agno_spec_builder import build as async_build
from agno_spec_builder.builders.agents import MODEL_PROVIDERS
from agno_spec_builder.schemas import StepConfig


def build(*args, **kwargs):
    return asyncio.run(async_build(*args, **kwargs))


def workflow_spec(router: dict) -> dict:
    return {
        "models": {"default": {"provider": "fake", "id": "offline"}},
        "agents": [
            {"name": "Tech Researcher", "model": {"id": "default"}},
            {"name": "Finance Researcher", "model": {"id": "default"}},
        ],
        "workflows": [{"name": "Adaptive Research", "steps": [router]}],
    }


class RouterWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.previous_fake = MODEL_PROVIDERS.get("fake")
        MODEL_PROVIDERS["fake"] = "tests.fake_provider:FakeModel"

    def tearDown(self):
        if self.previous_fake is None:
            MODEL_PROVIDERS.pop("fake", None)
        else:
            MODEL_PROVIDERS["fake"] = self.previous_fake

    def test_router_builds_and_selects_regular_step_choices(self):
        runtime = build(
            workflow_spec(
                {
                    "name": "research_router",
                    "router": 'input.contains("tech") ? "tech_research" : "finance_research"',
                    "choices": [
                        {"name": "tech_research", "run": "agent.tech-researcher"},
                        {"name": "finance_research", "run": "agent.finance-researcher"},
                    ],
                }
            )
        )

        router = runtime.workflows["adaptive-research"].steps[0]
        self.assertIsInstance(router, Router)
        self.assertEqual([choice.name for choice in router.choices], ["tech_research", "finance_research"])
        self.assertTrue(all(isinstance(choice, Step) for choice in router.choices))

        router._prepare_steps()
        selected = router._route_steps(StepInput(input="latest tech news"))
        self.assertEqual([choice.name for choice in selected], ["tech_research"])

    def test_router_selector_can_choose_from_native_step_choices(self):
        runtime = build(
            workflow_spec(
                {
                    "name": "research_router",
                    "router": "step_choices[1]",
                    "choices": [
                        {"name": "tech_research", "run": "agent.tech-researcher"},
                        {"name": "finance_research", "run": "agent.finance-researcher"},
                    ],
                }
            )
        )

        router = runtime.workflows["adaptive-research"].steps[0]
        router._prepare_steps()
        selected = router._route_steps(StepInput(input="market outlook"))
        self.assertEqual([choice.name for choice in selected], ["finance_research"])

    def test_router_accepts_native_loop_choices(self):
        runtime = build(
            workflow_spec(
                {
                    "name": "research_router",
                    "router": '"deep_research"',
                    "choices": [
                        {"name": "quick_research", "run": "agent.finance-researcher"},
                        {
                            "name": "deep_research",
                            "repeat": [{"name": "research_pass", "run": "agent.tech-researcher"}],
                            "until": "current_iteration >= 2",
                            "max_iterations": 3,
                        },
                    ],
                }
            )
        )

        router = runtime.workflows["adaptive-research"].steps[0]
        self.assertIsInstance(router.choices[0], Step)
        self.assertIsInstance(router.choices[1], Loop)
        self.assertEqual(router.choices[1].end_condition, "current_iteration >= 2")
        self.assertEqual(router.choices[1].max_iterations, 3)

        router._prepare_steps()
        selected = router._route_steps(StepInput(input="deep tech"))
        self.assertEqual(selected, [router.choices[1]])

    def test_router_accepts_keyed_branches_without_nested_names(self):
        config = StepConfig.model_validate(
            {
                "name": "research_route",
                "router": 'input.contains("tech") ? "tech" : "finance"',
                "branches": {
                    "tech": {"run": "agent.tech-researcher"},
                    "finance": {"run": "agent.finance-researcher"},
                },
            }
        )
        self.assertEqual([branch.name for branch in config.branches.values()], ["tech", "finance"])

        runtime = build(workflow_spec(config.model_dump(exclude_defaults=True)))
        router = runtime.workflows["adaptive-research"].steps[0]
        self.assertIsInstance(router, Router)
        self.assertEqual([choice.name for choice in router.choices], ["tech", "finance"])

        router._prepare_steps()
        selected = router._route_steps(StepInput(input="latest tech news"))
        self.assertEqual([choice.name for choice in selected], ["tech"])

    def test_router_true_builds_selector_free_user_input_router(self):
        runtime = build(
            workflow_spec(
                {
                    "name": "choose_route",
                    "router": True,
                    "branches": {
                        "tech": {"run": "agent.tech-researcher"},
                        "finance": {"run": "agent.finance-researcher"},
                    },
                    "requires_user_input": True,
                    "user_input_message": "Choose a research path",
                    "allow_multiple_selections": False,
                }
            )
        )

        router = runtime.workflows["adaptive-research"].steps[0]
        self.assertIsInstance(router, Router)
        self.assertIsNone(router.selector)
        self.assertTrue(router.requires_user_input)
        self.assertEqual(router.user_input_message, "Choose a research path")
        self.assertFalse(router.allow_multiple_selections)
        self.assertEqual([choice.name for choice in router.choices], ["tech", "finance"])

    def test_router_true_uses_compact_implicit_hitl_syntax(self):
        runtime = build(
            workflow_spec(
                {
                    "name": "choose_route",
                    "router": True,
                    "message": "Choose a research path",
                    "branches": {
                        "tech": {"run": "agent.tech-researcher"},
                        "finance": {"run": "agent.finance-researcher"},
                    },
                    "hitl": {
                        "allow_multiple_selections": False,
                        "max_retries": 5,
                        "on_reject": "retry",
                    },
                }
            )
        )

        router = runtime.workflows["adaptive-research"].steps[0]
        self.assertIsNone(router.selector)
        self.assertTrue(router.requires_user_input)
        self.assertEqual(router.user_input_message, "Choose a research path")
        self.assertFalse(router.allow_multiple_selections)
        self.assertEqual(router.hitl_max_retries, 5)
        self.assertEqual(router.on_reject, "retry")

    def test_router_choice_schema_rejects_ambiguous_or_invalid_declarations(self):
        choice = {"name": "one", "run": "agent.one"}
        with self.assertRaisesRegex(ValidationError, "needs non-empty `branches` or `choices`"):
            StepConfig.model_validate({"name": "route", "router": '"one"'})
        with self.assertRaisesRegex(ValidationError, "either `choices` or `branches`"):
            StepConfig.model_validate(
                {"name": "route", "router": '"one"', "choices": [choice], "branches": {"one": choice}}
            )
        with self.assertRaisesRegex(ValidationError, "choice names must be unique"):
            StepConfig.model_validate({"name": "route", "router": '"one"', "choices": [choice, choice]})
        with self.assertRaisesRegex(ValidationError, "only valid on a router"):
            StepConfig.model_validate({"name": "not_a_router", "run": "agent.one", "choices": [choice]})
        implicit_hitl = StepConfig.model_validate(
            {"name": "route", "router": True, "branches": {"one": choice}}
        )
        self.assertTrue(implicit_hitl.requires_user_input)
        with self.assertRaisesRegex(ValidationError, "requires `requires_user_input: true`"):
            StepConfig.model_validate(
                {"name": "route", "router": True, "branches": {"one": choice}, "requires_user_input": False}
            )
        with self.assertRaisesRegex(ValidationError, "cannot require user input"):
            StepConfig.model_validate(
                {
                    "name": "route",
                    "router": '"one"',
                    "branches": {"one": choice},
                    "requires_user_input": True,
                }
            )
        with self.assertRaisesRegex(ValidationError, "only valid with `router: true`"):
            StepConfig.model_validate(
                {
                    "name": "route",
                    "router": '"one"',
                    "branches": {"one": choice},
                    "allow_multiple_selections": True,
                }
            )
        with self.assertRaisesRegex(ValidationError, "cannot be combined"):
            StepConfig.model_validate(
                {
                    "name": "route",
                    "router": True,
                    "branches": {"one": choice},
                    "message": "Choose one",
                    "user_input_message": "Legacy message",
                }
            )
        with self.assertRaisesRegex(ValidationError, "only valid with `router: true`"):
            StepConfig.model_validate(
                {
                    "name": "route",
                    "router": '"one"',
                    "branches": {"one": choice},
                    "hitl": {"message": "Choose one"},
                }
            )
        for invalid_router in (False, 1):
            with self.subTest(router=invalid_router), self.assertRaises(ValidationError):
                StepConfig.model_validate(
                    {"name": "route", "router": invalid_router, "branches": {"one": choice}}
                )
        with self.assertRaisesRegex(ValidationError, "either `router` or `case`"):
            StepConfig.model_validate(
                {"name": "route", "router": '"one"', "case": '"one"', "branches": {"one": choice}}
            )

    def test_case_branches_remain_available_for_simple_single_route_dispatch(self):
        runtime = build(
            workflow_spec(
                {
                    "name": "research_case",
                    "case": 'input.contains("tech") ? "tech" : "finance"',
                    "branches": {
                        "tech": {"name": "tech_branch", "run": "agent.tech-researcher"},
                        "finance": {"name": "finance_branch", "run": "agent.finance-researcher"},
                    },
                }
            )
        )

        case_step = runtime.workflows["adaptive-research"].steps[0]
        self.assertIsInstance(case_step, Step)
        self.assertIsNotNone(case_step.executor)


if __name__ == "__main__":
    unittest.main()
