"""Small synchronous bridge to the official Streamable HTTP MCP client.

Gemini invokes synchronous Python tools. Each call owns and closes its HTTP
connection, MCP session and async event loop, including on timeout/cancellation.
The logical search session stays stable across calls on this client.

Written against the mcp 2.x SDK, which `requirements.txt` pins exactly. The
transport's shape is version-specific in two ways that fail loudly rather than
subtly, so the pin is not decoration: 2.x yields two streams where 1.x yielded
three, and takes an `httpx2.AsyncClient` where 1.x took an `httpx.AsyncClient`.
"""

import json
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation
from pydantic import BaseModel, field_validator

MCP_URL = "https://search.parallel.ai/mcp"
USER_AGENT = "competitor-research-agent/1.0 (+https://github.com/sravya520/competitor-research-agent)"


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
        raise ValueError("Parallel retrieval requires an HTTP or HTTPS URL")
    return url


class MCPDocument(BaseModel):
    url: str
    title: str | None = None
    excerpts: list[str]
    full_content: str | None = None

    _valid_url = field_validator("url")(validate_url)


class _Response(BaseModel):
    results: list[MCPDocument]


class ParallelMCPClient:
    def __init__(self, timeout: float = 45):
        self.timeout = timeout
        self.session_id = uuid4().hex

    def call(self, tool: str, arguments: dict) -> list[MCPDocument]:
        try:
            return anyio.run(self._call, tool, arguments)
        except BaseExceptionGroup as exc:
            # Task groups wrap single failures. Preserve the useful service or
            # transport error for CLI callers and the UI's existing error log.
            cause = exc
            while isinstance(cause, BaseExceptionGroup) and len(cause.exceptions) == 1:
                cause = cause.exceptions[0]
            raise cause from None

    async def _call(self, tool: str, arguments: dict) -> list[MCPDocument]:
        # No auth, ambient credentials or endpoint override: this client always
        # uses the public anonymous service. The deadline covers discovery too.
        with anyio.fail_after(self.timeout):
            async with httpx2.AsyncClient(
                headers={"User-Agent": USER_AGENT}, timeout=self.timeout,
            ) as http:
                # Two streams, not three: 2.x dropped the session-id callback
                # that 1.x yielded alongside them.
                async with streamable_http_client(MCP_URL, http_client=http) as (read, write):
                    async with ClientSession(
                        read, write,
                        client_info=Implementation(name="competitor-research-agent", version="1.0"),
                    ) as session:
                        await session.initialize()
                        available = await session.list_tools()
                        if tool not in {item.name for item in available.tools}:
                            raise RuntimeError(f"Parallel MCP does not provide {tool}")
                        result = await session.call_tool(
                            tool, {**arguments, "session_id": self.session_id},
                        )
                        if result.is_error:
                            message = " ".join(
                                block.text for block in result.content if block.type == "text"
                            )
                            raise RuntimeError(f"Parallel MCP {tool} failed: {message}")
                        data = result.structured_content
                        if data is None:
                            # MCP permits JSON in a text block when structured
                            # output is unavailable; do not parse human prose.
                            texts = [block.text for block in result.content if block.type == "text"]
                            if len(texts) != 1:
                                raise ValueError("Parallel MCP returned no structured result")
                            data = json.loads(texts[0])
                        return _Response.model_validate(data, strict=True).results
