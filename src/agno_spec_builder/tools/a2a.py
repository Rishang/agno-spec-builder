"""A2A client toolkit for calling remote agents as tools."""

import re
from typing import Any, Literal
from urllib.parse import urlparse

from agno.client.a2a import A2AClient
from agno.tools import Toolkit

from agno_spec_builder.utils import expand_env


def _default_name(url: str) -> str:
    """Create a stable toolkit name without performing remote agent-card discovery."""
    parsed = urlparse(url)
    raw = f"{parsed.netloc}{parsed.path}".strip("/") or url
    return f"a2a_{re.sub(r'[^A-Za-z0-9_]+', '_', raw).strip('_').lower()}"


class A2ATools(Toolkit):
    """Expose a remote A2A agent through one asynchronous tool call."""

    def __init__(
        self,
        url: str,
        name: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        protocol: Literal["rest", "json-rpc"] = "rest",
        **kwargs: Any,
    ) -> None:
        self.url = url
        self.headers = expand_env(headers or {})
        self.timeout = timeout
        self.protocol = protocol
        self.client = A2AClient(url, timeout=timeout, protocol=protocol)
        super().__init__(name=name or _default_name(url), tools=[self.ask], **kwargs)

    async def ask(
        self,
        message: str,
        context_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Send a message to this toolset's configured remote A2A endpoint."""
        response = await self.client.send_message(
            message,
            context_id=context_id,
            user_id=user_id,
            metadata=metadata,
            headers=self.headers,
        )
        return response.content
