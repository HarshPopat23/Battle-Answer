"""Persistent MCP v1 sessions on an owned event-loop thread, using the official SDK."""

import asyncio
from concurrent.futures import Future
from contextlib import AsyncExitStack
from datetime import timedelta
import json
import os
from pathlib import Path
import queue
import threading

from .config import ArenaError


def local_refs_only(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('$ref', '$dynamicRef') and (not isinstance(child, str) or not child.startswith('#')):
                raise ArenaError('MCP schema contains an external reference; remote schema fetching is disabled.')
            local_refs_only(child)
    elif isinstance(value, list):
        for child in value:
            local_refs_only(child)


def resolve_env(mapping):
    result = {}
    for name, reference in (mapping or {}).items():
        if reference not in os.environ:
            raise ArenaError('Missing MCP environment reference: ' + reference)
        result[name] = os.environ[reference]
    return result


class MCPBridge:
    def __init__(self, servers, workspace, approve=None):
        self.servers = servers
        self.workspace = Path(workspace).resolve()
        self.approve = approve
        self.queue = queue.Queue()
        self.closed = False
        self.routes = {}
        self.timeout = max((s.timeout for s in servers), default=30) * max(1, len(servers)) + 15
        self.thread = threading.Thread(target=self._thread, daemon=True)
        self.thread.start()

    def _thread(self):
        asyncio.run(self._serve())

    async def _serve(self):
        sessions, catalog = {}, {}
        async with AsyncExitStack() as stack:
            while True:
                item = await asyncio.to_thread(self.queue.get)
                if item is None:
                    return
                operation, args, future = item
                try:
                    for server in self.servers:
                        if server.name not in sessions:
                            async with asyncio.timeout(server.timeout):
                                sessions[server.name], catalog[server.name] = await self._connect(server, stack)
                    if operation == 'list':
                        result = catalog
                    else:
                        server, tool, arguments = args
                        async with asyncio.timeout(server.timeout):
                            response = await sessions[server.name].call_tool(tool, arguments=arguments)
                        result = response.model_dump(mode='json', by_alias=True, exclude_none=True)
                    future.set_result(result)
                except ArenaError as exc:
                    future.set_exception(exc)
                except Exception:
                    # SDK exceptions can contain subprocess environments, URLs, or auth headers.
                    future.set_exception(ArenaError('MCP operation failed or timed out. Check the configured server and its advertised schema; writes are not retried.'))

    async def _connect(self, server, stack):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamable_http_client
            import httpx
        except ImportError:
            raise ArenaError('Install MCP support: pip install -e ".[mcp]"') from None
        if server.command:
            home = self.workspace.parent / ('.mcp-home-' + server.name)
            home.mkdir(exist_ok=True, mode=0o700)
            env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(home), 'USERPROFILE': str(home)}
            env.update(resolve_env(server.env))
            params = StdioServerParameters(command=server.command, args=list(server.args), env=env, cwd=str(self.workspace))
            errlog = await stack.enter_async_context(_stderr_sink())
            read, write = await stack.enter_async_context(stdio_client(params, errlog=errlog))
        else:
            client = await stack.enter_async_context(httpx.AsyncClient(
                headers=resolve_env(server.headers), timeout=server.timeout, trust_env=False))
            read, write, _ = await stack.enter_async_context(streamable_http_client(server.url, http_client=client))
        session = await stack.enter_async_context(ClientSession(read, write, read_timeout_seconds=timedelta(seconds=server.timeout)))
        await session.initialize()
        tools, cursor, seen = {}, None, set()
        while True:
            page = await session.list_tools(cursor=cursor)
            for tool in page.tools:
                if tool.name in tools:
                    raise ArenaError('MCP server returned duplicate tool names.')
                tools[tool.name] = {'description': (tool.description or '')[:1000], 'inputSchema': tool.inputSchema}
                if len(tools) > 500:
                    raise ArenaError('MCP server exposes too many tools.')
            cursor = page.nextCursor
            if not cursor:
                break
            if cursor in seen:
                raise ArenaError('MCP discovery repeated a pagination cursor.')
            seen.add(cursor)
        return session, tools

    def request(self, operation, *args):
        if self.closed or not self.thread.is_alive():
            raise ArenaError('MCP session is closed.')
        future = Future()
        self.queue.put((operation, args, future))
        try:
            return future.result(timeout=self.timeout)
        except TimeoutError:
            raise ArenaError('MCP session deadline reached; inspect external server state before retrying a write.') from None

    def discover(self):
        return self.request('list')

    def available(self):
        catalog, exposed = self.discover(), {}
        for server in self.servers:
            for name in (*server.read_tools, *server.write_tools):
                if name not in catalog[server.name]:
                    raise ArenaError(f'Configured MCP tool is not advertised: {server.name}/{name}')
                record = catalog[server.name][name]
                local_refs_only(record['inputSchema'])
                public_name = 'mcp_' + server.name + '__' + name
                if public_name in exposed:
                    raise ArenaError('MCP tool names collide; rename the configured servers.')
                exposed[public_name] = record
                self.routes[public_name] = (server, name)
        if len(json.dumps(exposed)) > 100000:
            raise ArenaError('Selected MCP catalog is too large; enable fewer tools.')
        return exposed

    def call(self, name, arguments):
        tools = self.available()
        if name not in tools:
            raise ArenaError('MCP tool is not explicitly enabled.')
        server, tool = self.routes[name]
        try:
            import jsonschema
            from referencing import Registry
            validator = jsonschema.validators.validator_for(tools[name]['inputSchema'])
            validator.check_schema(tools[name]['inputSchema'])
            def no_remote_schema(uri):
                raise ArenaError('Remote schema retrieval is disabled.')
            validator(tools[name]['inputSchema'], registry=Registry(retrieve=no_remote_schema)).validate(arguments)
        except ImportError:
            raise ArenaError('Install the MCP extra, including jsonschema.') from None
        except Exception:
            raise ArenaError('Arguments do not satisfy the MCP tool schema; no request was sent.') from None
        if tool in server.write_tools and (not self.approve or not self.approve(name, arguments)):
            raise ArenaError('MCP write requires explicit approval; no request was sent.')
        result = self.request('call', server, tool, arguments)
        if result.get('isError'):
            # Do not label a server-reported failure as successful tool evidence.
            raise ArenaError('MCP server reported a tool error: ' + json.dumps(result.get('content', []), ensure_ascii=False)[:12000])
        return result

    def close(self):
        if not self.closed:
            self.closed = True
            self.queue.put(None)
            self.thread.join(timeout=self.timeout)


from contextlib import asynccontextmanager


@asynccontextmanager
async def _stderr_sink():
    # External server logs may contain credentials; do not copy them into model context.
    with open(os.devnull, 'w') as fh:
        yield fh
