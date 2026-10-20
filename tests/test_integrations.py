"""Actual Chromium and official MCP SDK transports; no model keys or external sites."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import site
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from arena.browser import BrowserSession
from arena.config import ArenaError, Browser, MCPServer
from arena.mcp_bridge import MCPBridge, local_refs_only
from arena.server import make_server
from test_assistant import ApprovalSession, config, wait_for

FIXTURE = str(Path(__file__).parent / 'fixtures' / 'mcp_server.py')
REQUIRE = os.environ.get('ARENA_REQUIRE_INTEGRATION') == '1'


def dependency(test, name):
    if importlib.util.find_spec(name) is None:
        if REQUIRE:
            raise AssertionError('Required integration dependency missing: ' + name)
        raise unittest.SkipTest(name + ' extra not installed')


class MCP(unittest.TestCase):
    def setUp(self):
        dependency(self, 'mcp')
        dependency(self, 'jsonschema')
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name) / 'workspace'
        self.work.mkdir()
        self.bridges = []
        self.env_patch = patch.dict(os.environ, {'ARENA_FIXTURE_PYTHONPATH': site.getusersitepackages()})
        self.env_patch.start()

    def tearDown(self):
        for bridge in self.bridges:
            bridge.close()
            self.assertFalse(bridge.thread.is_alive(), 'MCP transport did not close')
        self.env_patch.stop()
        self.temp.cleanup()

    def bridge(self, server, approve=None):
        bridge = MCPBridge((server,), self.work, approve)
        self.bridges.append(bridge)
        return bridge

    def test_stdio_state_schema_environment_and_explicit_selection(self):
        settings = MCPServer('fixture', command=sys.executable, args=(FIXTURE,),
                             env={'EXPLICIT_VALUE': 'ARENA_EXPLICIT_TEST_VALUE', 'PYTHONPATH': 'ARENA_FIXTURE_PYTHONPATH'},
                             read_tools=('increment', 'environment'), timeout=10)
        with patch.dict(os.environ, {'ARENA_EXPLICIT_TEST_VALUE': 'fixture-value', 'ARENA_UNRELATED_TEST_KEY': 'not-forwarded'}):
            bridge = self.bridge(settings)
            self.assertIn('write_note', bridge.discover()['fixture'])
            self.assertNotIn('mcp_fixture__write_note', bridge.available())
            with self.assertRaises(ArenaError):
                bridge.call('mcp_fixture__increment', {'amount': 'invalid'})
            self.assertEqual(bridge.call('mcp_fixture__increment', {'amount': 2})['structuredContent']['result'], 2)
            self.assertEqual(bridge.call('mcp_fixture__increment', {'amount': 3})['structuredContent']['result'], 5)
            values = json.loads(bridge.call('mcp_fixture__environment', {})['content'][0]['text'])
            self.assertEqual(values['explicit'], 'fixture-value')
            self.assertIsNone(values['unrelated'])
            self.assertIn('.mcp-home-fixture', values['home'])

    def test_write_approval_is_required_and_errors_are_not_success(self):
        approved = []
        bridge = self.bridge(MCPServer('fixture', command=sys.executable, args=(FIXTURE,), env={'PYTHONPATH': 'ARENA_FIXTURE_PYTHONPATH'},
                                      read_tools=('broken',), write_tools=('write_note',), timeout=10),
                             approve=lambda name, args: approved.append(name) or False)
        with self.assertRaises(ArenaError):
            bridge.call('mcp_fixture__write_note', {'text': 'denied'})
        self.assertFalse((self.work / 'note.txt').exists())
        bridge.approve = lambda name, args: True
        bridge.call('mcp_fixture__write_note', {'text': 'approved'})
        self.assertEqual((self.work / 'note.txt').read_text(), 'approved')
        with self.assertRaisesRegex(ArenaError, 'server reported a tool error'):
            bridge.call('mcp_fixture__broken', {})
        self.assertEqual(approved, ['mcp_fixture__write_note'])

    def test_server_prefixes_do_not_misroute_tools(self):
        a = MCPServer('x', command=sys.executable, args=(FIXTURE,), env={'PYTHONPATH': 'ARENA_FIXTURE_PYTHONPATH'}, read_tools=('increment',), timeout=10)
        b = MCPServer('x__nested', command=sys.executable, args=(FIXTURE,), env={'PYTHONPATH': 'ARENA_FIXTURE_PYTHONPATH'}, read_tools=('increment',), timeout=10)
        bridge = MCPBridge((a, b), self.work)
        self.bridges.append(bridge)
        self.assertEqual(bridge.call('mcp_x__nested__increment', {'amount': 4})['structuredContent']['result'], 4)
        self.assertEqual(bridge.call('mcp_x__increment', {'amount': 1})['structuredContent']['result'], 1)

    def test_external_schema_refs_and_unadvertised_tools_fail_closed(self):
        with self.assertRaises(ArenaError):
            local_refs_only({'properties': {'x': {'$ref': 'https://example.com/schema'}}})
        bridge = self.bridge(MCPServer('fixture', command=sys.executable, args=(FIXTURE,), env={'PYTHONPATH': 'ARENA_FIXTURE_PYTHONPATH'}, read_tools=('invented',), timeout=10))
        with self.assertRaises(ArenaError):
            bridge.available()

    def test_streamable_http_session(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        with subprocess.Popen([sys.executable, FIXTURE, str(port)], cwd=self.work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
            try:
                def ready():
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.1):
                            return True
                    except OSError:
                        return False
                wait_for(ready)
                bridge = self.bridge(MCPServer('remote', url=f'http://127.0.0.1:{port}/mcp', read_tools=('increment',), timeout=10))
                self.assertEqual(bridge.call('mcp_remote__increment', {'amount': 7})['structuredContent']['result'], 7)
                self.assertEqual(bridge.call('mcp_remote__increment', {'amount': 1})['structuredContent']['result'], 8)
                bridge.close()
            finally:
                process.terminate()
                process.wait(timeout=5)


class BrowserIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dependency(cls, 'playwright')
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                options = {'headless': True}
                if os.environ.get('ARENA_TEST_CHROMIUM'):
                    options['executable_path'] = os.environ['ARENA_TEST_CHROMIUM']
                browser = p.chromium.launch(**options)
                browser.close()
        except Exception as exc:
            if REQUIRE:
                raise
            raise unittest.SkipTest('Install Chromium to run browser integration tests: ' + type(exc).__name__)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(('GET', self.path))
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', f'http://localhost:{self.server.server_port}/outside')
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'''<html><head><title>Browser fixture</title></head><body>
                <h1>Fixture</h1><label>Name <input aria-label="Name"></label>
                <button onclick="document.querySelector('#status').textContent='Hello '+document.querySelector('input').value">Greet</button>
                <button onclick="fetch('/save',{method:'POST',body:'approved'}).then(()=>document.querySelector('#status').textContent='Saved')">Save</button>
                <a href="/popup" target="_blank">New tab</a><p id="status">Ready</p>
                <script>console.log('fixture loaded');setTimeout(()=>fetch('/unapproved',{method:'POST'}).catch(()=>{}),50);</script>
                </body></html>''')

            def do_POST(self):
                owner.requests.append(('POST', self.path))
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        settings = Browser(enabled=True, origins=(self.base,), timeout_ms=3000, executable_path=os.environ.get('ARENA_TEST_CHROMIUM', ''))
        self.approvals = []
        self.browser = BrowserSession(settings, self.root / 'artifacts', lambda n, a: self.approvals.append(n) or True)

    def tearDown(self):
        self.browser.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_dynamic_browser_actions_screenshot_tabs_and_evidence(self):
        snapshot = self.browser.call('browser_navigate', {'url': self.base})
        refs = {element['label']: element['ref'] for element in snapshot['elements']}
        self.browser.call('browser_fill', {'ref': refs['Name'], 'text': 'Arena'})
        self.browser.call('browser_click', {'ref': refs['Greet']})
        self.assertIn('Hello Arena', self.browser.call('browser_snapshot', {})['text'])
        self.browser.call('browser_click', {'ref': refs['Save']})
        self.browser.page.locator('#status').get_by_text('Saved', exact=True).wait_for()
        self.assertIn(('POST', '/save'), self.requests)
        image = self.browser.call('browser_screenshot', {})
        self.assertEqual((self.root / 'artifacts' / image['artifact']).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        with self.browser.context.expect_page() as popup:
            self.browser.call('browser_click', {'ref': refs['New tab']})
        popup.value.wait_for_load_state()
        self.assertEqual(len(self.browser.call('browser_tabs', {})['tabs']), 2)
        self.assertEqual(self.browser.call('browser_switch_tab', {'index': 1})['title'], 'Browser fixture')
        evidence = self.browser.call('browser_evidence', {})
        self.assertTrue(any('fixture loaded' in line['text'] for line in evidence['console']))
        self.assertTrue(any(line['url'].endswith('/save') for line in evidence['network']))
        self.assertEqual(len(self.approvals), 4)

    def test_origin_redirect_and_unapproved_mutations_are_blocked(self):
        snapshot = self.browser.call('browser_navigate', {'url': self.base})
        self.browser.page.wait_for_timeout(150)
        self.assertNotIn(('POST', '/unapproved'), self.requests)
        self.browser.approve = lambda *args: False
        ref = next(e['ref'] for e in snapshot['elements'] if e['label'] == 'Save')
        with self.assertRaises(ArenaError):
            self.browser.call('browser_click', {'ref': ref})
        self.assertNotIn(('POST', '/save'), self.requests)
        with self.assertRaises(ArenaError):
            self.browser.call('browser_navigate', {'url': f'http://localhost:{self.server.server_port}/outside'})
        with self.assertRaises(ArenaError):
            self.browser.call('browser_navigate', {'url': self.base + '/redirect'})
        self.assertNotIn(('GET', '/outside'), self.requests)

    def test_chat_ui_can_submit_and_approve_in_real_browser(self):
        from playwright.sync_api import sync_playwright
        server = make_server(config(), self.root, {}, port=0, session_factory=ApprovalSession)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, **({'executable_path': os.environ['ARENA_TEST_CHROMIUM']} if os.environ.get('ARENA_TEST_CHROMIUM') else {}))
                page = browser.new_page(viewport={'width': 390, 'height': 844})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.get_by_label('Your task', exact=True).fill('Save the fixture')
                page.get_by_role('button', name='Run task').click()
                page.get_by_role('button', name='Approve this action').click(timeout=5000)
                page.locator('#answer').get_by_text('Approved', exact=True).wait_for(timeout=5000)
                self.assertFalse(errors)
                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
