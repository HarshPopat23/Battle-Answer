"""Compose the original local tools with explicitly enabled browser and MCP sessions."""

from .browser import BrowserSession, SCHEMAS as BROWSER_TOOLS
from .config import ArenaError
from .context import read_document
from .mcp_bridge import MCPBridge
from .tools import Tools


class Capabilities(Tools):
    def __init__(self, workspace, config, allow_exec=False, read_only=False, *, artifacts,
                 allow_browser=False, allow_mcp=False, approve=None, context=None):
        super().__init__(workspace, config, allow_exec, read_only)
        self.browser = None
        self.mcp = None
        self.context_store = context
        self.artifacts = artifacts
        if allow_browser and not read_only:
            if not config.browser.enabled:
                raise ArenaError('Browser requires browser.enabled=true and --allow-browser.')
            self.browser = BrowserSession(config.browser, artifacts, approve)
        if allow_mcp and config.mcp_servers and not read_only:
            self.mcp = MCPBridge(config.mcp_servers, self.root, approve)

    def available(self):
        result = super().available()
        result['read_document'] = {'path': 'relative PDF, DOCX, or UTF-8 text document'}
        if self.context_store:
            result['context_search'] = {'query': 'project source terms to retrieve'}
            result['history_search'] = {'query': 'terms from earlier conversation turns'}
        if self.browser:
            result.update(BROWSER_TOOLS)
        if self.mcp:
            result.update(self.mcp.available())
        return result

    def call(self, name, args):
        if name == 'read_document':
            if set(args) != {'path'}:
                raise ArenaError('read_document needs exactly path.')
            try:
                return read_document(self.resolve(args['path']))
            except ArenaError:
                raise
            except Exception:
                raise ArenaError('Document extraction failed; use a supported, unencrypted document.') from None
        if name in ('context_search', 'history_search') and self.context_store:
            if set(args) != {'query'}:
                raise ArenaError('Search needs exactly query.')
            return self.context_store.search(args['query']) if name == 'context_search' else self.context_store.history_search(args['query'])
        if name.startswith('browser_') and self.browser:
            return self.browser.call(name, args)
        if name.startswith('mcp_') and self.mcp:
            return self.mcp.call(name, args)
        return super().call(name, args)

    def close(self):
        if self.browser:
            self.browser.close()
        if self.mcp:
            self.mcp.close()
