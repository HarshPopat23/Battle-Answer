"""Wire contracts, tool boundaries, weak-model failures, and resumable tournaments."""

from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from arena.agents import Agent, Budget
from arena.config import ArenaError, Config, Model, load
from arena.providers import Client, ProviderError, Reply
from arena.runner import Runner, create_run, lock_run
from arena.tools import Tools, snapshot
from arena.validation import parse_json, validate_result


def score(n, fatal=False):
    return dict(correctness=n, completeness=n, specificity=n, robustness=n, clarity=n,
                fatal=fatal, fatal_evidence='Reproducing input demonstrates a broken requirement.' if fatal else '')


def encoded(result):
    return Reply(json.dumps({'action': 'answer', 'result': result}), 20, 20)


def cfg(**kwargs):
    model = Model('ollama', 'test-model', max_output_tokens=512, retries=0)
    return Config(worker=model, judge=model, **kwargs)


class FakeClient:
    """Deterministic provider double, not evidence of real model quality."""
    requests = 0
    fail_at = None

    def __init__(self, model):
        self.model = model

    def generate(self, messages, before_request):
        before_request()
        type(self).requests += 1
        if self.fail_at == self.requests:
            raise ProviderError('Injected provider failure')
        prompt = messages[-1]['content']
        if prompt.startswith('Return {"ok"'):
            return Reply('{"ok":true,"product":42}', 10, 10)
        data = json.loads(messages[1]['content'])
        phase = data['phase']
        if phase == 'competitor':
            return encoded({'solution': 'Salt winds cross the sea. A complete candidate.'})
        if phase == 'attacker':
            return encoded({'attacks': [{'severity': 'MINOR', 'claim': 'Could be more specific.', 'evidence': 'No concrete example.'}]})
        if phase == 'defender':
            return encoded({'defense': 'Concede the lack of specificity; added an example.', 'solution': 'Salt winds cross the sea; for example, waves leave salt on rocks.'})
        # Always score the same content equally, so swapping orientation stays deterministic.
        return encoded({'scores': {'X': score(8), 'Y': score(8)}, 'winner': 'X', 'reason': 'Both satisfy the test task.'})


class Temp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        FakeClient.requests = 0
        FakeClient.fail_at = None

    def tearDown(self):
        self.temp.cleanup()


class ConfigTests(Temp):
    def test_unknown_provider_and_remote_plain_http_rejected(self):
        with self.assertRaises(ArenaError):
            Model('unknown', 'model')
        with self.assertRaises(ArenaError):
            Model('openai-compatible', 'model', api_base='http://example.com/v1')
        with self.assertRaises(ArenaError):
            Model('groq', 'model', api_base='https://user:secret@example.com/v1')

    def test_invalid_limits_and_secret_fields_rejected(self):
        with self.assertRaises(ArenaError):
            cfg(agents=True)
        with self.assertRaises(ArenaError):
            cfg(judge_votes=3)
        path = self.root / 'bad.toml'
        path.write_text('[worker]\nprovider="groq"\nmodel="test"\napi_key="not-allowed"\n')
        with self.assertRaises(ArenaError):
            load(path)

    def test_examples_load_without_api_keys(self):
        for path in (Path(__file__).parents[1] / 'examples').glob('*.toml'):
            self.assertIsInstance(load(path), Config)


class WireTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        self.response = {}
        self.status = 200
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.received.append((self.path, {k.lower(): v for k, v in self.headers.items()}, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(owner.status)
                self.end_headers()
                self.wfile.write(json.dumps(owner.response).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}/v1'
        self.env = patch.dict(os.environ, {'TEST_ARENA_KEY': 'fixture-only-key'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def client(self, provider):
        return Client(Model(provider, 'test-model', self.base, 'TEST_ARENA_KEY', retries=0))

    def test_openai_compatible_wire(self):
        self.response = {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}],
                         'usage': {'prompt_tokens': 11, 'completion_tokens': 7}}
        for provider in ('openai', 'groq', 'openrouter', 'ollama', 'openai-compatible'):
            reply = self.client(provider).generate([{'role': 'user', 'content': 'hello'}])
            path, headers, body = self.received[-1]
            self.assertEqual(path, '/v1/chat/completions')
            self.assertEqual(headers['authorization'], 'Bearer fixture-only-key')
            self.assertEqual(body['model'], 'test-model')
            self.assertEqual(reply.input_tokens + reply.output_tokens, 18)
            self.assertNotIn('temperature', body)

    def test_anthropic_wire(self):
        self.response = {'content': [{'type': 'text', 'text': 'ok'}], 'stop_reason': 'end_turn',
                         'usage': {'input_tokens': 5, 'output_tokens': 3}}
        reply = self.client('anthropic').generate([{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'hello'}])
        path, headers, body = self.received[-1]
        self.assertEqual(path, '/v1/messages')
        self.assertEqual(body['system'], 'rules')
        self.assertEqual(headers['x-api-key'], 'fixture-only-key')
        self.assertEqual(reply.text, 'ok')

    def test_gemini_wire_and_reasoning_usage(self):
        self.response = {'candidates': [{'content': {'parts': [{'text': 'private thought', 'thought': True}, {'text': 'ok'}]}, 'finishReason': 'STOP'}],
                         'usageMetadata': {'promptTokenCount': 5, 'totalTokenCount': 20, 'candidatesTokenCount': 3}}
        reply = self.client('gemini').generate([{'role': 'system', 'content': 'rules'}, {'role': 'user', 'content': 'hello'}])
        path, headers, body = self.received[-1]
        self.assertEqual(path, '/v1/models/test-model:generateContent')
        self.assertNotIn('fixture-only-key', path)
        self.assertEqual(headers['x-goog-api-key'], 'fixture-only-key')
        self.assertIn('systemInstruction', body)
        self.assertEqual((reply.text, reply.output_tokens), ('ok', 15))

    def test_truncation_and_auth_errors_fail_without_echoing_body(self):
        self.response = {'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}]}
        with self.assertRaises(ProviderError):
            self.client('groq').generate([{'role': 'user', 'content': 'hello'}])
        self.status, self.response = 401, {'error': 'fixture-only-key'}
        with self.assertRaises(ProviderError) as raised:
            self.client('groq').generate([{'role': 'user', 'content': 'hello'}])
        self.assertNotIn('fixture-only-key', str(raised.exception))


class ToolTests(Temp):
    def setUp(self):
        super().setUp()
        self.work = self.root / 'work'
        self.tool = Tools(self.work, cfg())

    def test_write_search_read_and_path_guards(self):
        self.tool.call('write_file', {'path': 'src/main.py', 'content': 'hello world\n'})
        self.assertEqual(self.tool.read_file('src/main.py')['content'], 'hello world\n')
        self.assertEqual(self.tool.search_text('world')['matches'][0]['line'], 1)
        for path in ('../outside', '/etc/passwd', '.env', '.env.local', '.git/config', 'private.key'):
            with self.assertRaises(ArenaError):
                self.tool.resolve(path)

    def test_symlinks_and_disabled_tools(self):
        try:
            (self.work / 'link').symlink_to(self.root)
            has_symlink = True
        except OSError:
            has_symlink = False
        if has_symlink:
            with self.assertRaises(ArenaError):
                self.tool.resolve('link/file')
        with self.assertRaises(ArenaError):
            self.tool.call('run_command', {'argv': ['echo', 'bad']})
        readonly = Tools(self.work, cfg(), read_only=True)
        with self.assertRaises(ArenaError):
            readonly.call('write_file', {'path': 'x', 'content': 'bad'})
        with self.assertRaises(ArenaError):
            self.tool.call('fetch_url', {'url': 'https://example.com'})

    def test_snapshot_excludes_secrets_symlinks_and_own_run(self):
        (self.work / 'ok.py').write_text('pass\n')
        (self.work / '.env').write_text('KEY=secret')
        (self.work / 'credentials.json').write_text('{}')
        try:
            (self.work / 'link').symlink_to(self.root)
        except OSError:
            pass
        target = self.work / 'run' / 'source'
        target.mkdir(parents=True)
        snapshot(self.work, target)
        self.assertEqual(sorted(p.name for p in target.iterdir()), ['ok.py'])

    def test_docker_is_explicit_and_uses_resource_network_controls(self):
        tool = Tools(self.work, cfg(), allow_exec=True)
        calls = []

        class Process:
            def __init__(self, argv, **kwargs):
                calls.append(argv)
                self.stdout = io.BytesIO(b'test output')

            def wait(self, **kwargs):
                return 0

        with patch('arena.tools.shutil.which', return_value='/bin/docker'), patch('arena.tools.subprocess.Popen', Process):
            self.assertEqual(tool.call('run_command', {'argv': ['python', '-V']})['exit_code'], 0)
        self.assertIn('--network=none', calls[0])
        self.assertIn('--read-only', calls[0])
        self.assertIn('--pull=never', calls[0])
        self.assertEqual(calls[0][-2:], ['python', '-V'])
        self.assertNotIn('shell', calls[0])


class ProtocolTests(Temp):
    def budget(self, config):
        return Budget(config, self.root / 'usage.json', self.root / 'audit.jsonl')

    def test_judge_missing_nan_and_out_of_range_scores_rejected(self):
        for s in ({}, {'X': score(8), 'Y': score(11)}, {'X': score(True), 'Y': score(8)}):
            with self.assertRaises(ArenaError):
                validate_result('judge', {'scores': s, 'winner': 'X', 'reason': 'x'})
        with self.assertRaises(ArenaError):
            parse_json('{"score":NaN}')

    def test_repair_fallback_and_secret_redaction(self):
        primary = Model('ollama', 'weak', max_output_tokens=512)
        fallback = Model('ollama', 'strong', max_output_tokens=512)
        config = Config(primary, primary, fallback=fallback, repair_attempts=1)
        seen = []

        class ClientDouble:
            def __init__(self, model):
                self.model = model

            def generate(self, messages, before_request):
                before_request()
                seen.append(self.model.model)
                return Reply('bad response', 1, 1) if self.model.model == 'weak' else encoded({'solution': 'fixed'})

        result = Agent(config, self.budget(config), ClientDouble).run('competitor', {'task': 't'}, None, 'test')
        self.assertEqual(result['solution'], 'fixed')
        self.assertEqual(seen, ['weak', 'weak', 'strong'])

    def test_malformed_output_pauses_instead_of_fabricating_winner(self):
        config = cfg(repair_attempts=0)

        class Broken(FakeClient):
            def generate(self, messages, before_request):
                before_request()
                return Reply('not JSON', 1, 1)

        with self.assertRaises(ArenaError):
            Agent(config, self.budget(config), Broken).run('judge', {}, None, 'j')

    def test_hard_request_budget(self):
        config = cfg(max_calls=1)
        budget = self.budget(config)
        agent = Agent(config, budget, FakeClient)
        agent.doctor(config.worker, 'first')
        with self.assertRaises(ArenaError):
            agent.doctor(config.worker, 'second')
        self.assertEqual(budget.state['requests'], 1)

    def test_key_values_are_redacted_in_saved_responses(self):
        model = Model('groq', 'test', api_key_env='TEST_ARENA_SECRET')
        config = Config(model, model)

        class Echo(FakeClient):
            def generate(self, messages, before_request):
                before_request()
                return encoded({'solution': 'fixture-sensitive-value'})

        with patch.dict(os.environ, {'TEST_ARENA_SECRET': 'fixture-sensitive-value'}):
            result = Agent(config, self.budget(config), Echo).run('competitor', {}, None, 'redact')
        self.assertEqual(result['solution'], '[REDACTED]')
        self.assertNotIn('fixture-sensitive-value', (self.root / 'audit.jsonl').read_text())


class EndToEnd(Temp):
    def run_arena(self, n, baseline=None):
        directory = self.root / ('run-' + str(n))
        config = cfg(agents=n)
        create_run(directory, 'Write a sentence about salt and sea.', config, baseline=baseline, seed=7)
        with redirect_stdout(io.StringIO()):
            report = Runner(directory, config, FakeClient).drive()
        return directory, config, report

    def test_tournaments_with_byes_and_baseline(self):
        for n in (1, 2, 5):
            directory, config, report = self.run_arena(n, 'The sea.' if n == 5 else None)
            self.assertEqual(report['agents'], n)
            self.assertEqual(report['status'], 'needs_review')
            self.assertTrue((directory / 'winner.md').is_file())
            self.assertTrue((directory / 'winner.patch').is_file())
            if n == 5:
                self.assertIsNotNone(report['baseline_comparison']['result'])
            requests = FakeClient.requests
            with redirect_stdout(io.StringIO()):
                Runner(directory, config, FakeClient).drive()
            self.assertEqual(FakeClient.requests, requests, 'completed resume must not spend tokens')

    def test_interruption_resume_reuses_completed_jobs(self):
        directory = self.root / 'interrupted'
        config = cfg(agents=2, concurrency=1)
        create_run(directory, 'Task', config, seed=1)
        FakeClient.fail_at = 4
        with redirect_stdout(io.StringIO()), self.assertRaises(ProviderError):
            Runner(directory, config, FakeClient).drive()
        completed = (directory / 'jobs/a001.spawn.json').read_bytes()
        FakeClient.fail_at = None
        with redirect_stdout(io.StringIO()):
            report = Runner(directory, config, FakeClient).drive()
        self.assertEqual((directory / 'jobs/a001.spawn.json').read_bytes(), completed)
        self.assertIsNotNone(report['champion'])

    def test_unreceipted_nonempty_output_is_not_complete(self):
        directory = self.root / 'partial'
        config = cfg(agents=1)
        state = create_run(directory, 'Task', config)
        output = Path(state['agents']['a001']['solution'])
        output.parent.mkdir()
        output.write_text('partial write before crash')
        with redirect_stdout(io.StringIO()):
            Runner(directory, config, FakeClient).drive()
        self.assertNotEqual(output.read_text(), 'partial write before crash')

    def test_mutated_task_and_output_cannot_be_resumed(self):
        directory, config, _ = self.run_arena(2)
        task = directory / 'task.md'
        old = task.read_text()
        task.write_text('changed')
        with self.assertRaises(ArenaError):
            Runner(directory, config, FakeClient)
        task.write_text(old)
        (directory / 'r0/a001.md').write_text('tampered')
        with self.assertRaises(ArenaError):
            Runner(directory, config, FakeClient)

    def test_config_changes_and_parallel_process_lock(self):
        directory = self.root / 'locked'
        config = cfg(agents=2)
        create_run(directory, 'Task', config)
        with self.assertRaises(ArenaError):
            Runner(directory, replace(config, worker=replace(config.worker, model='different')))
        with lock_run(directory), self.assertRaises(ArenaError):
            with lock_run(directory):
                pass

    def test_real_tool_loop_edits_only_copy_and_exports_applicable_patch(self):
        source = self.root / 'project'
        source.mkdir()
        (source / 'main.py').write_text("print('old')")
        directory = self.root / 'coding-run'
        config = cfg(agents=2)
        create_run(directory, 'Change main.py to print hello.', config, workspace=source)

        class Editor(FakeClient):
            def generate(self, messages, before_request):
                if messages[-1]['content'].startswith('Return {"ok"'):
                    return super().generate(messages, before_request)
                phase = json.loads(messages[1]['content'])['phase']
                if phase == 'competitor' and len(messages) == 2:
                    before_request()
                    type(self).requests += 1
                    return Reply(json.dumps({'action': 'tool', 'name': 'write_file',
                                             'arguments': {'path': 'main.py', 'content': "print('hello')"}}), 20, 20)
                return super().generate(messages, before_request)

        with redirect_stdout(io.StringIO()):
            report = Runner(directory, config, Editor).drive()
        self.assertEqual((source / 'main.py').read_text(), "print('old')")
        self.assertEqual(report['changed_files'], ['main.py'])
        self.assertEqual((Path(report['workspace']) / 'main.py').read_text(), "print('hello')")
        checked = subprocess.run(['git', 'apply', '--check', str(directory / 'winner.patch')], cwd=source, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_verified_failure_cannot_beat_passed_candidate(self):
        directory = self.root / 'verified'
        config = cfg(agents=2, verify_argv=('python', '-m', 'unittest'))
        create_run(directory, 'Task', config, allow_exec=True)
        runner = Runner(directory, config, FakeClient)
        # Keep the full orchestration but substitute the unavailable Docker daemon.
        def verify(tool, argv):
            return {'exit_code': 0 if tool.root.name == 'a002' else 1, 'timed_out': False, 'output': 'independent check'}
        with patch.object(runner, 'preflight'), patch.object(Tools, 'run_command', verify), redirect_stdout(io.StringIO()):
            report = runner.drive()
        self.assertEqual(report['champion'], 'a002')
        self.assertEqual(report['status'], 'passed_configured_checks')


if __name__ == '__main__':
    unittest.main()
