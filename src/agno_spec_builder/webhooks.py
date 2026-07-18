"""FastAPI routes for declarative inbound webhooks."""

import asyncio
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import jmespath
from fastapi import FastAPI, HTTPException, Request, status

from agno_spec_builder.schemas.webhook import WebhookConfig, WebhookTrigger
from agno_spec_builder.utils import expand_env

if TYPE_CHECKING:
    from agno_spec_builder.builder import Built

WebhookHandler = Callable[[Request], Awaitable[dict[str, Any]]]


def _compiled_triggers(webhook: WebhookConfig) -> list[tuple[WebhookTrigger, Any]]:
    return [(trigger, jmespath.compile(trigger.match.field) if trigger.match else None) for trigger in webhook.triggers]


def _handler(runtime: "Built", webhook: WebhookConfig) -> WebhookHandler:
    """Create a route handler with resolved secrets and match expressions."""
    secret = expand_env(webhook.secret)
    triggers = _compiled_triggers(webhook)

    async def handle(request: Request) -> dict[str, Any]:
        provided_secret = request.headers.get(webhook.secret_header)
        if provided_secret is None or not hmac.compare_digest(provided_secret, secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook secret")
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid JSON payload",
            ) from error

        payload_text = json.dumps(payload, indent=2, sort_keys=True, default=str)
        matched: list[WebhookTrigger] = []
        for trigger, expression in triggers:
            if expression is None or (trigger.match is not None and expression.search(payload) == trigger.match.value):
                matched.append(trigger)

        async def invoke(trigger: WebhookTrigger) -> dict[str, Any]:
            targets = {
                "agent": runtime.agents,
                "team": runtime.teams,
                "workflow": runtime.workflows,
            }
            target = targets[trigger.kind][trigger.name]
            result = await runtime.mcp_runner.arun_target(target, trigger.prompt.replace("{payload}", payload_text))
            return {"trigger": trigger.name, "kind": trigger.kind, "target": trigger.name, "analysis": result}

        results = await asyncio.gather(*(invoke(trigger) for trigger in matched))
        return {"ok": True, "matched": len(results), "results": results}

    return handle


def attach_webhook_routes(app: FastAPI, runtime: "Built") -> FastAPI:
    """Attach configured webhook routes to an existing FastAPI application."""
    existing_paths = {getattr(route, "path", None) for route in app.routes}
    for webhook in runtime.webhooks.values():
        if webhook.endpoint in existing_paths:
            raise ValueError(f"webhook path {webhook.endpoint!r} conflicts with an existing FastAPI route")
        app.add_api_route(
            webhook.endpoint,
            _handler(runtime, webhook),
            methods=["POST"],
            name=f"webhook-{webhook.name}",
        )
        existing_paths.add(webhook.endpoint)
    return app
