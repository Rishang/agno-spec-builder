import asyncio
import logging
from collections.abc import Callable
from typing import Any, cast

import jmespath
from agno.agent import Agent
from agno.db.base import BaseDb
from agno.run.agent import CustomEvent, RunOutput
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.workflow import Loop, Parallel, Router, Step, StepOutput, Workflow
from pydantic import BaseModel

from agno_spec_builder.builders.schemas import SchemaBuilder
from agno_spec_builder.mcp.toolkit import McpRunner
from agno_spec_builder.schemas import StepConfig, WorkflowConfig
from agno_spec_builder.utils import resolve
from agno_spec_builder.workflow.cel import CELUtil
from agno_spec_builder.workflow.store import FanoutStateStore, InMemoryFanoutStore

log = logging.getLogger(__name__)

# Agno's own hard cap on Step(workflow=...) nesting (_MAX_NESTED_WORKFLOW_DEPTH in
# agno.workflow.step) is enforced at run time via a ContextVar — a long acyclic chain of
# `run: workflow.<slug>` refs builds fine here and only blows up mid-run once agno's
# internal cap kicks in. Mirror the same limit in _ensure() so it fails at build time.
_MAX_WORKFLOW_REF_DEPTH = 10

# Run-completed event `event` values whose `.content` is the child's final output.
# One of these arrives last per run (a team's TeamRunCompleted follows its members'
# RunCompleted), so last-wins capture yields the outermost run's content — the same
# value arun_target() would have returned.
_COMPLETED_CONTENT_EVENTS = frozenset({"RunCompleted", "TeamRunCompleted", "WorkflowCompleted"})


class FanoutPaused(Exception):
    """Signal the workflow's native error-pause path after saving branch state."""


def _paused_output(data: dict) -> RunOutput | TeamRunOutput:
    return TeamRunOutput.from_dict(data["output"]) if data["kind"] == "team" else RunOutput.from_dict(data["output"])


async def _stream_capture(obj, inp: str, sink: dict, runner: McpRunner):
    """Stream a child agent/team/workflow's run events (so tool calls, skill loads,
    reasoning and content deltas reach the wire) while capturing its final content
    into sink['content'] — the streaming twin of mcp_runner.arun_target()."""
    async for ev in runner.astream_target(obj, inp):
        if isinstance(ev, (RunOutput, TeamRunOutput)):
            sink["run_output"] = ev
            sink["content"] = ev.content
            continue
        if getattr(ev, "event", None) in _COMPLETED_CONTENT_EVENTS:
            content = getattr(ev, "content", None)
            if content is not None:
                sink["content"] = content
        yield ev


async def _run_and_emit(obj, inp: str, c: StepConfig, ns: dict, runner: McpRunner):
    """Shared tail of `run`/`case` steps: stream obj's run events, then emit an
    optional `emit`-derived CustomEvent, then the step's final StepOutput."""
    sink: dict = {}
    async for ev in _stream_capture(obj, inp, sink, runner):
        yield ev
    result = sink.get("content")
    if event := _emit(c, ns, result):
        yield event
    yield StepOutput(content=result)


def _ns(step_input) -> dict:
    return {name: _json(out.content) for name, out in (step_input.previous_step_outputs or {}).items()}


def _json(content):
    """JMESPath needs plain JSON; structured output arrives as a Pydantic model."""
    return content.model_dump(mode="json") if isinstance(content, BaseModel) else content


def _jmespath(expr: str | None):
    return jmespath.compile(expr) if expr else None


def _named_branch(key: str, c: StepConfig) -> StepConfig:
    """Router addresses choices by step name, but authors think in `branches` keys.
    Return a copy of the branch step named after its key so a `router:` CEL
    selector can return the key and hit the right choice."""
    return c if c.name == key else c.model_copy(update={"name": key})


def _apply_when(when_expr: CELUtil | None, ns: dict) -> bool:
    return when_expr is None or when_expr.check(ns)


def _emit(c: StepConfig, ns: dict, result) -> CustomEvent | None:
    """Evaluate `emit` over prior outputs + this step's own result: log it and
    return a CustomEvent for the executor to yield into the NDJSON stream."""
    if not c.emit:
        return None
    value = jmespath.compile(c.emit).search({**ns, "result": _json(result)})
    log.info(f"{c.name}: {value}")
    return CustomEvent(step_name=c.name, data=value)


class WorkflowStepBuilder:
    """Compiles a single StepConfig into an agno Step/Parallel.

    Grammar (one of `run` / `parallel` / `case` per step):
      - run: "agent.<slug>" | "team.<slug>" | "workflow.<slug>"  -> Step(agent|team|workflow=...)
      - parallel: [ <step>, ... ]             -> Parallel(...) static branches
      - case: "<CEL expr>"                    -> Step(executor=...) routes to matching branch
        branches: { key: <step>, ... }

    Modifiers on a `run` step:
      - loop: "<jmespath>"    fan-out: run the agent/team/workflow once per item in
                              the JMESPath result (over prior named outputs), in parallel.
      - when: "<CEL expr>"    skip this step if the expression is falsy.
      - input: "<jmespath>"   transform prior outputs into this step's input string.
      - emit: "<jmespath>"    log.info + stream a CustomEvent, evaluated over prior
                              outputs plus this step's own `result`.

    CEL expressions (when/case) see prior named step outputs as top-level variables.
    JMESPath expressions (loop/input/emit) resolve against the same namespace.
    Every step's `name` is required, unique, and [A-Za-z0-9_].

    This builder doesn't own workflow lifecycle (registry, cycle detection) — a
    `run: workflow.<slug>` ref is resolved via `resolve_workflow`, supplied by the
    owning WorkflowBuilder, so declaration order and circular-ref checks stay there.
    """

    def __init__(
        self,
        agents: dict[str, Agent],
        teams: dict[str, Team],
        resolve_workflow: Callable[[str], Workflow],
        mcp_runner: McpRunner,
        fanout_store: FanoutStateStore,
    ):
        self.agents = agents
        self.teams = teams
        self._resolve_workflow = resolve_workflow
        self.mcp_runner = mcp_runner
        self.fanout_store = fanout_store

    def build(self, c: StepConfig) -> Step | Parallel:
        return self._m_one(c)

    def _m_one(self, c: StepConfig):
        if c.parallel is not None:
            return Parallel(*(self._m_one(s) for s in c.parallel), name=c.name)
        if c.repeat is not None:
            return self._m_repeat(c)
        if c.router is not None:
            return self._m_router(c)
        if c.case is not None:
            return self._m_case(c)
        if c.loop:
            return self._m_loop(c)
        return self._m_run(c)

    def _resolve(self, c: StepConfig) -> Agent | Team | Workflow:
        kind, slug = c.kind_ref
        if kind == "workflow":
            return self._resolve_workflow(slug)
        (obj,) = resolve([slug], self.agents if kind == "agent" else self.teams)
        return obj

    def _m_run(self, c: StepConfig) -> Step:
        obj = self._resolve(c)
        # MCP agents need invoke-time tool injection; when/input/emit need custom executors too.
        if c.when or c.input or c.emit or (isinstance(obj, Agent) and self.mcp_runner.needs(obj)):
            when_expr = CELUtil(c.when) if c.when else None
            input_expr = _jmespath(c.input)

            async def run_exec(step_input):
                ns = _ns(step_input)
                if not _apply_when(when_expr, ns):
                    yield StepOutput(content=None)
                    return
                inp = str(input_expr.search(ns) or "") if input_expr else str(step_input.input or "")
                # Stream the child's run events (tool calls, skill loads, reasoning,
                # content deltas) onto the wire instead of collapsing to .content the
                # way arun_target() does — otherwise a step with when/input/emit/MCP
                # goes silent in the UI while the plain-Step path streams fine.
                async for out in _run_and_emit(obj, inp, c, ns, self.mcp_runner):
                    yield out

            return Step(name=c.name, executor=run_exec, **c.step_kwargs())

        if isinstance(obj, Agent):
            return Step(name=c.name, agent=obj, **c.step_kwargs())
        if isinstance(obj, Team):
            return Step(name=c.name, team=obj, **c.step_kwargs())
        # nested workflow: agno's native support — the whole sub-workflow runs as
        # this step's executor, events and all.
        assert isinstance(obj, Workflow)
        return Step(name=c.name, workflow=obj, **c.step_kwargs())

    def _m_case(self, c: StepConfig) -> Step:
        """CEL `case` expression -> string key -> dispatch to matching branch."""
        assert c.case  # guaranteed: _m_one only calls this when c.case is not None
        case_expr = CELUtil(c.case)
        case_label = c.case  # copy the string — the closure below only needs the label
        branch_objs = {k: self._resolve(v) for k, v in c.branches.items()}

        async def case_exec(step_input):
            ns = _ns(step_input)
            key = str(case_expr.eval(ns) or "")
            obj = branch_objs.get(key)
            if obj is None:
                log.warning(f"case {case_label!r} = {key!r}: no branch matched")
                yield StepOutput(content=None)
                return
            async for out in _run_and_emit(obj, str(step_input.input or ""), c, ns, self.mcp_runner):
                yield out

        return Step(name=c.name, executor=case_exec, **c.step_kwargs())

    def _m_router(self, c: StepConfig) -> Router:
        """agno-native Router: a CEL `router` selector returns a `branches` key (or
        list of keys); the matching branch step(s) run. Unlike `case` (a custom
        single-dispatch executor), this is agno's Router node, so it supports
        native multi-selection and step-level HITL (requires_confirmation /
        human_review, passed through via step_kwargs) that a raw executor can't.
        Each branch is named after its key so the CEL selector can address it."""
        assert c.router  # guaranteed by _m_one
        choices = [self._m_one(_named_branch(k, v)) for k, v in c.branches.items()]
        return Router(name=c.name, selector=c.router, choices=choices, **c.step_kwargs())

    def _m_repeat(self, c: StepConfig) -> Loop:
        """agno-native Loop: run `repeat` sub-steps until the `until` CEL
        end_condition is true or `max_iterations` is hit. Condition-driven
        iteration — distinct from `loop` (JMESPath fan-out over a fixed list)."""
        assert c.repeat is not None  # guaranteed by _m_one
        return Loop(
            name=c.name,
            steps=[self._m_one(s) for s in c.repeat],
            end_condition=c.until or None,
            max_iterations=c.max_iterations,
            **c.step_kwargs(),
        )

    def _m_loop(self, c: StepConfig) -> Step:
        """Dynamic fan-out: JMESPath `loop` over prior named outputs gives a list;
        run `run`'s agent/team once per item, in parallel under a semaphore.
        """
        assert c.loop
        obj = self._resolve(c)
        loop_expr = jmespath.compile(c.loop)
        input_expr = _jmespath(c.input)
        when_expr = CELUtil(c.when) if c.when else None

        async def fan_out(step_input, run_context):
            ns = _ns(step_input)
            if not _apply_when(when_expr, ns):
                yield StepOutput(content=None)
                return
            items = loop_expr.search(ns) or []
            if not items:
                log.warning(f"loop {c.loop!r} produced no items — nothing to run")
                yield StepOutput(content=[])
                return

            # `run_context.run_id` is the workflow run id, stable across native
            # error-pause/retry. Persist every completed and paused branch before
            # raising, so a restart or UI feedback never replays finished work.
            run_id = run_context.run_id
            state = self.fanout_store.load(run_id) or {
                "items": items,
                "results": [None] * len(items),
                "paused": {},
            }
            base_input = str(input_expr.search(ns)) if input_expr else None
            sem = asyncio.Semaphore(c.max_parallel)
            queue: asyncio.Queue = asyncio.Queue()
            done = object()

            async def one(index, item):
                if state["results"][index] is not None:
                    return
                async with sem:
                    sink: dict = {}
                    inp = base_input if base_input is not None else str(item)
                    try:
                        paused = state["paused"].get(str(index))
                        events = (
                            cast(Any, obj).acontinue_run(
                                run_response=_paused_output(paused),
                                stream=True,
                                stream_events=True,
                                yield_run_output=True,
                            )
                            if paused
                            else self.mcp_runner.astream_target(obj, inp, yield_run_output=True)
                        )
                        async for ev in events:
                            if isinstance(ev, (RunOutput, TeamRunOutput)):
                                sink["run_output"] = ev
                                sink["content"] = ev.content
                                continue
                            await queue.put(("ev", ev))
                    except Exception as e:  # fail-soft, reported below
                        await queue.put(("err", e))
                        return
                    output = sink.get("run_output")
                    if output is not None and output.is_paused:
                        await queue.put(("paused", (index, output)))
                    else:
                        await queue.put(("res", (index, sink.get("content"))))

            async def driver():
                await asyncio.gather(*(one(i, item) for i, item in enumerate(state["items"])), return_exceptions=True)
                await queue.put(done)

            task = asyncio.create_task(driver())
            try:
                while (msg := await queue.get()) is not done:
                    kind, payload = msg
                    if kind == "ev":
                        yield payload
                    elif kind == "res":
                        index, result = payload
                        state["results"][index] = result
                        state["paused"].pop(str(index), None)
                    elif kind == "paused":
                        index, output = payload
                        state["paused"][str(index)] = {
                            "kind": "team" if isinstance(output, TeamRunOutput) else "agent",
                            "output": output.to_dict(),
                        }
                    else:  # "err" — one dead branch shouldn't sink the run
                        log.warning(f"loop branch failed: {payload}")
            finally:
                await task

            self.fanout_store.save(run_id, getattr(run_context, "workflow_id", "") or "", c.name, state)
            if state["paused"]:
                questions = []
                for index, data in state["paused"].items():
                    paused = _paused_output(data)
                    for req in paused.active_requirements:
                        if req.pause_type == "user_feedback" and req.user_feedback_schema:
                            for question in req.user_feedback_schema:
                                item = question.to_dict()
                                item["question"] = f"[Branch {int(index) + 1}] {item['question']}"
                                questions.append(item)
                yield CustomEvent(
                    step_name=c.name,
                    data={"type": "fanout_feedback", "run_id": run_id, "questions": questions},
                )
                raise FanoutPaused(f"{c.name} is awaiting feedback from {len(state['paused'])} branch(es)")

            results = state["results"]
            self.fanout_store.delete(run_id)
            if event := _emit(c, ns, results):
                yield event
            yield StepOutput(content=results)

        kwargs = c.step_kwargs()
        kwargs["on_error"] = "pause"
        return Step(name=c.name, executor=cast(Any, fan_out), **kwargs)


class WorkflowBuilder:
    """Builds agno Workflows from WorkflowConfigs.

    Owns workflow lifecycle only: the slug -> spec catalog, lazy/recursive
    building (a `workflow.<slug>` ref points at another entry in the top-level
    `workflows:` list, so declaration order doesn't matter), the build-in-progress
    registry, and circular/over-deep ref detection. Per-step compilation (the
    run/parallel/case/loop grammar) is delegated to WorkflowStepBuilder — a
    circular ref raises instead of looping.
    """

    def __init__(
        self,
        agents: dict[str, Agent],
        teams: dict[str, Team],
        schemas: SchemaBuilder,
        db: BaseDb,
        specs: list[WorkflowConfig],
        mcp_runner: McpRunner | None = None,
        fanout_store: FanoutStateStore | None = None,
    ):
        self.schemas = schemas
        self.db = db
        self._specs = {c.slug: c for c in specs}
        self.registry: dict[str, Workflow] = {}
        self._building: set[str] = set()  # slugs mid-build, for cycle detection
        self._steps = WorkflowStepBuilder(
            agents, teams, self._ensure, mcp_runner or McpRunner(), fanout_store or InMemoryFanoutStore()
        )
        for slug in self._specs:
            self._ensure(slug)

    def _ensure(self, slug: str) -> Workflow:
        if slug in self.registry:
            return self.registry[slug]
        if slug in self._building:
            raise ValueError(f"Circular workflow ref: {slug}")
        if slug not in self._specs:
            raise ValueError(f"Unknown workflow {slug!r}. Available: {list(self._specs)}")
        if len(self._building) >= _MAX_WORKFLOW_REF_DEPTH:
            chain = " -> ".join((*self._building, slug))
            raise ValueError(
                f"workflow ref chain nests more than {_MAX_WORKFLOW_REF_DEPTH} levels deep "
                f"(agno's max nested-workflow depth): {chain}"
            )
        self._building.add(slug)
        try:  # finally: a failed build must not leave the slug stuck mid-build
            self.registry[slug] = self._build(self._specs[slug])
        finally:
            self._building.discard(slug)
        return self.registry[slug]

    def _build(self, cfg: WorkflowConfig) -> Workflow:
        return Workflow(
            id=cfg.slug,
            name=cfg.name,
            description=cfg.description,
            db=self.db,
            steps=[self._steps.build(c) for c in cfg.steps],
            **cfg.workflow_kwargs(),
        )
