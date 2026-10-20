"""Single-agent assistance, persistent context, and explicit routing to Arena when useful."""

import json
from pathlib import Path
import threading
import time

from .agents import Agent, Budget, atomic_json, digest
from .capabilities import Capabilities
from .config import ArenaError
from .context import ContextStore
from .providers import Client
from .runner import Runner, config_identity, create_run, lock_run
from .tools import snapshot


ROLES = {
    'general': 'Answer the actual request. Use tools when evidence is needed. Cite source paths or URLs you actually inspected; distinguish assumptions from verified facts.',
    'coder': 'Inspect relevant code first, make a minimal change, run meaningful configured checks when available, and explain the resulting diff and unresolved failures.',
    'researcher': 'Build a source-backed answer. Prefer primary documentation, record exact URLs, compare conflicting evidence, and do not present simulation outputs as real observations.',
    'reviewer': 'Find reproducible defects and explain their impact with file paths and evidence. Do not change files unless the user explicitly requested fixes.',
}


def choose_mode(task, mode):
    if mode not in ('auto', 'single', 'arena'):
        raise ArenaError('mode must be auto, single, or arena.')
    if mode != 'auto':
        return mode
    # Transparent, deliberately conservative policy; no hidden model call or cost.
    phrases = ('compare alternatives', 'competing solutions', 'run a tournament', 'use arena', 'debate approaches')
    return 'arena' if any(phrase in task.lower() for phrase in phrases) else 'single'


class AssistantSession:
    def __init__(self, directory, config, workspace=None, *, allow_exec=False,
                 allow_browser=False, allow_mcp=False, approve=None, on_event=None, client_factory=Client):
        self.directory = Path(directory).resolve()
        self.config = config
        self.workspace_source = str(Path(workspace).resolve()) if workspace else None
        self.permissions = {'allow_exec': allow_exec, 'allow_browser': allow_browser, 'allow_mcp': allow_mcp}
        self.approve = approve
        self.on_event = on_event or (lambda event: None)
        self.client_factory = client_factory
        if config.verify_argv and not allow_exec:
            raise ArenaError('Configured verification requires --allow-exec.')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.work = self.directory / 'workspace'
        self.source = self.directory / 'source'
        metadata = self.directory / 'session.json'
        identity = digest({'config': config_identity(config, allow_exec, allow_browser, allow_mcp),
                           'source': self.workspace_source, 'permissions': self.permissions})
        if metadata.exists():
            if json.loads(metadata.read_text())['identity'] != identity:
                raise ArenaError('Session workspace/model/tool settings changed; start a new session directory.')
        else:
            if self.workspace_source:
                snapshot(self.workspace_source, self.source)
                snapshot(self.source, self.work)
            else:
                self.source.mkdir(exist_ok=True)
                self.work.mkdir(exist_ok=True)
            atomic_json(metadata, {'identity': identity, 'source': self.workspace_source, 'permissions': self.permissions})
        self.context = ContextStore(self.directory / 'context.sqlite3')
        self.budget = Budget(config, self.directory / 'usage.json', self.directory / 'audit.jsonl')
        self.agent = Agent(config, self.budget, client_factory, self.on_event)

    def ask(self, task, mode='auto', role='general'):
        if not isinstance(task, str) or not task.strip() or len(task) > 30000:
            raise ArenaError('Task must contain 1-30000 characters.')
        if role not in ROLES:
            raise ArenaError('Unknown assistant role.')
        with lock_run(self.directory):
            selected = choose_mode(task, mode)
            self.on_event({'type': 'route', 'mode': selected})
            if selected == 'arena':
                run = self.directory / ('tournament-' + str(time.time_ns()))
                create_run(run, task, self.config, self.work, allow_exec=self.permissions['allow_exec'],
                           allow_browser=self.permissions['allow_browser'], allow_mcp=self.permissions['allow_mcp'])
                report = Runner(run, self.config, self.client_factory, approve=self.approve, on_event=self.on_event).drive()
                answer = (run / 'winner.md').read_text()
                self.context.remember(task, answer)
                return {'mode': selected, 'answer': answer, 'report': report, 'run': run.name}
            self.context.index(self.work)
            previous = self.context.recent()
            evidence = self.context.search(task[:1000])
            payload = {'task': task, 'role': role, 'instructions': ROLES[role],
                       'history': previous, 'project_evidence': evidence,
                       'scope': 'Tools edit only this session copy. Original source files remain unchanged. Use browser/MCP only within enabled permissions.'}
            tools = Capabilities(self.work, self.config, allow_exec=self.permissions['allow_exec'],
                                 artifacts=self.directory / 'artifacts', allow_browser=self.permissions['allow_browser'],
                                 allow_mcp=self.permissions['allow_mcp'], approve=self.approve, context=self.context)
            try:
                result = self.agent.run('assistant', payload, tools, 'assistant-' + str(time.time_ns()))
                verification = tools.run_command(list(self.config.verify_argv)) if self.config.verify_argv else None
            finally:
                tools.close()
            answer = result['solution']
            self.context.remember(task, answer)
            self.context.index(self.work)
            output = {'mode': selected, 'answer': answer, 'verification': verification,
                      'workspace': str(self.work), 'usage': self.budget.state,
                      'status': 'passed_configured_checks' if verification and verification['exit_code'] == 0 and not verification['timed_out'] else 'needs_review'}
            atomic_json(self.directory / 'last-answer.json', output)
            return output


_terminal_lock = threading.Lock()


def terminal_approval(name, args):
    import sys
    if not sys.stdin.isatty():
        return False
    with _terminal_lock:
        print('\nApproval required for ' + name + ': ' + json.dumps(args, ensure_ascii=False)[:2000])
        try:
            return input('Perform this action? [y/N] ').strip().lower() == 'y'
        except EOFError:
            return False
