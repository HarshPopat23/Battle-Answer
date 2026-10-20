"""End-to-end assistant turns, context isolation, documents, and local UI boundaries."""
from dataclasses import replace
import http.client
import json
import os
import re
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile
from unittest.mock import patch

from arena.agents import Agent, Budget
from arena.assistant import AssistantSession, choose_mode
from arena.config import ArenaError, Browser, Config, MCPServer, Model
from arena.context import ContextStore, read_document
from arena.providers import Reply
from arena.server import make_server


def config(**settings):
    model = Model('ollama', 'fixture', retries=0, max_output_tokens=512)
    return Config(worker=model, judge=model, **settings)


def wait_for(predicate, timeout=8):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        result = predicate()
        if result:
            return result
        time.sleep(.02)
    raise AssertionError('Timed out waiting for fixture condition')


class Temp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()


class Configuration(Temp):
    def test_mcp_credentials_redact_without_corrupting_home_paths(self):
        server = MCPServer('fixture', command='fixture', env={'HOME': 'TEST_HOME_PATH', 'TOKEN': 'TEST_MCP_TOKEN'},
                           headers={'Authorization': 'TEST_MCP_HEADER'})
        cfg = config(mcp_servers=(server,))
        with patch.dict(os.environ, {'TEST_HOME_PATH': '/home/fixture', 'TEST_MCP_TOKEN': 'fixture-token-123',
                                     'TEST_MCP_HEADER': 'Bearer fixture-header-456'}):
            agent = Agent(cfg, Budget(cfg, self.root / 'usage.json', self.root / 'audit.jsonl'))
            result = agent.redact('/home/fixture/project.py fixture-token-123 Bearer fixture-header-456')
        self.assertEqual(result, '/home/fixture/project.py [REDACTED] [REDACTED]')

    def test_permissions_are_explicit(self):
        for url in ('http://example.com', 'https://example.com/path', 'https://u:p@example.com', 'https://*.example.com'):
            with self.subTest(url=url), self.assertRaises((ArenaError, ValueError)):
                Browser(origins=(url,))
        for settings in (dict(command='python', url='https://example.com/mcp'),
                         dict(command='python', env={'KEY': 'literal-key!'}),
                         dict(command='python', read_tools=('write',), write_tools=('write',)),
                         dict(url='http://example.com/mcp')):
            with self.subTest(settings=settings), self.assertRaises(ArenaError):
                MCPServer('fixture', **settings)

    def test_context_is_project_scoped_and_persistent(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'auth.py').write_text('def authenticate():\n    return "token rotation"\n')
        (project / '.env').write_text('ROTATION=excluded-value')
        store = ContextStore(self.root / 'context.sqlite3')
        store.index(project)
        hit = store.search('authenticate rotation')[0]
        self.assertEqual((hit['source'], hit['first_line']), ('auth.py', 1))
        self.assertEqual(store.search('excluded-value'), [])
        store.remember('Which module rotates tokens?', 'auth.py handles token rotation.')
        reopened = ContextStore(store.path)
        self.assertEqual(reopened.recent()[0]['answer'], 'auth.py handles token rotation.')
        self.assertEqual(reopened.history_search('tokens')[0]['turn'], 1)
        with self.assertRaises(ArenaError):
            reopened.history_search(['bad query'])

    def test_documents_extract_text_without_execution(self):
        path = self.root / 'brief.docx'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="urn:test"><w:p><w:t>Customer requirements</w:t></w:p></w:document>')
        self.assertEqual(read_document(path)['text'], 'Customer requirements')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('word/document.xml', 'x' * (4 * 1024 * 1024 + 1))
        with self.assertRaises(ArenaError):
            read_document(path)

    def test_pdf_extraction(self):
        try:
            from pypdf import PdfWriter
            from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        except ImportError:
            self.skipTest('documents extra not installed')
        writer = PdfWriter()
        page = writer.add_blank_page(200, 200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 100 Td (Evidence from PDF) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        path = self.root / 'brief.pdf'
        writer.write(path)
        self.assertIn('Evidence from PDF', read_document(path)['text'])


class ScriptedClient:
    payloads = []

    def __init__(self, model):
        pass

    def generate(self, messages, before_request):
        before_request()
        data = json.loads(messages[1]['content'])
        type(self).payloads.append(data)
        if len(messages) == 2 and data['input']['task'] == 'Implement greeting':
            result = {'action': 'tool', 'name': 'write_file', 'arguments': {'path': 'hello.py', 'content': 'print("hello")\n'}}
        else:
            result = {'action': 'answer', 'result': {'solution': 'Implemented hello.py; no executable verification was configured.'}}
        return Reply(json.dumps(result), 100, 30)


class Assistant(Temp):
    def test_multi_turn_edits_use_session_copy_and_history(self):
        source = self.root / 'project'
        source.mkdir()
        (source / 'readme.txt').write_text('Greeting project')
        directory = self.root / 'session'
        ScriptedClient.payloads = []
        events = []
        session = AssistantSession(directory, config(), source, client_factory=ScriptedClient, on_event=events.append)
        result = session.ask('Implement greeting', role='coder')
        self.assertTrue((directory / 'workspace' / 'hello.py').exists())
        self.assertFalse((source / 'hello.py').exists())
        self.assertEqual(result['status'], 'needs_review')
        reopened = AssistantSession(directory, config(), source, client_factory=ScriptedClient)
        reopened.ask('Explain hello.py')
        payload = ScriptedClient.payloads[-1]['input']
        self.assertIn('Implemented hello.py', payload['history'][0]['answer'])
        self.assertTrue(any(hit['source'] == 'hello.py' for hit in payload['project_evidence']))
        self.assertTrue(any(e['type'] == 'tool' and e['ok'] for e in events))
        self.assertEqual(reopened.budget.state['requests'], 3)
        with self.assertRaises(ArenaError):
            AssistantSession(directory, config(), source, allow_mcp=True)

    def test_routing_is_transparent_and_overridable(self):
        self.assertEqual(choose_mode('Fix my failing test', 'auto'), 'single')
        self.assertEqual(choose_mode('Compare alternatives for a cache', 'auto'), 'arena')
        self.assertEqual(choose_mode('Compare alternatives', 'single'), 'single')


class ApprovalSession:
    def __init__(self, directory, config, approve, on_event, **settings):
        self.approve, self.event = approve, on_event

    def ask(self, task, mode, role):
        self.event({'type': 'tool', 'name': 'fixture', 'ok': True})
        allowed = self.approve('fixture_write', {'text': task})
        return {'mode': 'single', 'answer': 'Approved' if allowed else 'Denied', 'status': 'needs_review'}


class UI(Temp):
    def setUp(self):
        super().setUp()
        self.server = make_server(config(), self.root, {}, port=0, session_factory=ApprovalSession)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        status, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.token = re.search(r"const token='([a-f0-9]+)'", html.decode()).group(1)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        super().tearDown()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        connection.request(method, path, json.dumps(body) if body is not None else None, headers or {})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def post(self, path, data):
        return self.request('POST', path, data, {'Content-Type': 'application/json', 'X-Arena-Token': self.token})

    def test_host_origin_csrf_and_path_boundaries(self):
        self.assertEqual(self.request('GET', '/', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/state', headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('POST', '/api/ask', {'task': 'x'})[0], 403)
        self.assertEqual(self.request('GET', '/artifacts/../../session.json')[0], 404)
        self.assertEqual(self.post('/api/ask', {'task': ''})[0], 400)

    def test_approval_and_job_lifecycle(self):
        self.assertEqual(self.post('/api/ask', {'task': 'hello'})[0], 202)
        pending = wait_for(lambda: self.server.chat_state.view()['approval'])
        self.assertEqual(self.post('/api/ask', {'task': 'concurrent'})[0], 400)
        self.assertEqual(self.post('/api/approve', {'id': 'wrong', 'allow': True})[0], 400)
        self.assertEqual(self.post('/api/approve', {'id': pending['id'], 'allow': True})[0], 200)
        wait_for(lambda: not self.server.chat_state.view()['running'])
        self.assertEqual(self.server.chat_state.view()['answer']['answer'], 'Approved')
        self.assertEqual(self.post('/api/approve', {'id': pending['id'], 'allow': True})[0], 400)

    def test_concurrent_approvals_are_presented_serially(self):
        answers = []
        workers = [threading.Thread(target=lambda n=n: answers.append((n, self.server.chat_state.approve(n, {})))) for n in ('first', 'second')]
        for worker in workers:
            worker.start()
        ids = []
        for allow in (True, False):
            pending = wait_for(lambda: (p if (p := self.server.chat_state.view()['approval']) and p['id'] not in ids else None))
            ids.append(pending['id'])
            self.assertEqual(self.post('/api/approve', {'id': pending['id'], 'allow': allow})[0], 200)
        for worker in workers:
            worker.join(timeout=3)
        self.assertEqual(sorted(value for _, value in answers), [False, True])
