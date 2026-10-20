"""Command line interface for planning, readiness checks, execution, and resume."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

from .agents import Agent, Budget
from .config import ArenaError, load
from .runner import Runner, create_run


def plan(config, baseline=False):
    matches = config.agents - 1
    calls = config.agents + (4 + config.judge_votes) * matches + (config.judge_votes if baseline else 0)
    return {'agents': config.agents, 'matches': matches, 'judge_votes_per_match': config.judge_votes,
            'base_generation_requests': calls, 'preflight_requests': 2,
            'minimum_requests_new_run': calls + 2,
            'request_limit': config.max_calls, 'token_limit': config.max_total_tokens,
            'note': 'Tool turns, protocol repairs, fallback, and HTTP retries add requests. Tokens and currency cost depend on models and task size.'}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='arena', description='Standalone LLM solution tournaments. No Claude Code or plugin required.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'doctor', 'run', 'resume', 'ask', 'chat', 'serve', 'mcp-list'):
        p = sub.add_parser(name)
        p.add_argument('--config', default='arena.toml', help='TOML file; keys belong in environment variables.')
        if name in ('plan', 'run', 'ask', 'chat', 'serve'):
            p.add_argument('--agents', type=int, help='Override configured competitor count.')
        if name == 'plan':
            p.add_argument('--baseline', action='store_true', help='Include final comparison calls in the plan.')
        if name == 'doctor':
            p.add_argument('--dir', help='New directory for readiness usage/audit files.')
        if name == 'run':
            task = p.add_mutually_exclusive_group(required=True)
            task.add_argument('--task')
            task.add_argument('--task-file')
            p.add_argument('--workspace', help='Filtered project snapshot; original files stay unchanged.')
            p.add_argument('--baseline-file', help='Earlier answer to compare against the winner.')
            p.add_argument('--dir', help='New output directory; defaults to .arena/run-<timestamp>.')
            p.add_argument('--seed', type=int)
            p.add_argument('--allow-exec', action='store_true', help='Allow commands only inside a restricted Docker container.')
        if name == 'resume':
            p.add_argument('--dir', required=True)
        if name in ('run', 'ask', 'chat', 'serve'):
            p.add_argument('--allow-browser', action='store_true', help='Enable configured browser origins; interactions still need approval.')
            p.add_argument('--allow-mcp', action='store_true', help='Enable trusted configured MCP servers; writes still need approval.')
        if name in ('ask', 'chat', 'serve'):
            p.add_argument('--workspace', help='Project directory to copy and index; originals stay unchanged.')
            p.add_argument('--session', default='.arena/assistant', help='Persistent conversation/workspace directory.')
            p.add_argument('--allow-exec', action='store_true')
        if name in ('ask', 'chat'):
            p.add_argument('--mode', choices=('auto', 'single', 'arena'), default='auto')
            p.add_argument('--role', choices=('general', 'coder', 'researcher', 'reviewer'), default='general')
        if name == 'ask':
            p.add_argument('--task', required=True)
        if name == 'serve':
            p.add_argument('--port', type=int, default=8765)
        if name == 'mcp-list':
            p.add_argument('--allow-mcp', action='store_true', required=True)
    status = sub.add_parser('status')
    status.add_argument('--dir', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'status':
            directory = Path(args.dir)
            path = directory / 'report.json'
            if path.exists():
                print(path.read_text())
            else:
                state = json.loads((directory / 'arena.json').read_text())
                print(json.dumps({'champion': state['champion'], 'rounds': len(state['rounds']),
                                  'usage': json.loads((directory / 'usage.json').read_text()) if (directory / 'usage.json').exists() else {}}, indent=2))
            return 0
        config = load(args.config)
        if getattr(args, 'agents', None) is not None:
            config = replace(config, agents=args.agents)
        if args.command == 'plan':
            print(json.dumps(plan(config, args.baseline), indent=2))
            return 0
        if args.command == 'doctor':
            directory = Path(args.dir or Path('.arena') / ('doctor-' + str(time.time_ns())))
            directory.mkdir(parents=True, exist_ok=False, mode=0o700)
            agent = Agent(config, Budget(config, directory / 'usage.json', directory / 'audit.jsonl'))
            for name, model in (('worker', config.worker), ('judge', config.judge)):
                agent.doctor(model, 'doctor.' + name)
                print(f'{name}: API, JSON, and simple arithmetic check passed. This is not a capability benchmark.')
            return 0
        if args.command == 'mcp-list':
            from .mcp_bridge import MCPBridge
            with __import__('tempfile').TemporaryDirectory(prefix='arena-mcp-discovery-') as work:
                bridge = MCPBridge(config.mcp_servers, work)
                try:
                    print(json.dumps(bridge.discover(), indent=2))
                finally:
                    bridge.close()
            return 0
        if args.command in ('ask', 'chat', 'serve'):
            from .assistant import AssistantSession, terminal_approval
            settings = dict(workspace=args.workspace, allow_exec=args.allow_exec,
                            allow_browser=args.allow_browser, allow_mcp=args.allow_mcp)
            if args.command == 'serve':
                from .server import serve
                serve(config, args.session, port=args.port, settings=settings)
                return 0
            session = AssistantSession(args.session, config, **settings, approve=terminal_approval)
            if args.command == 'ask':
                print(json.dumps(session.ask(args.task, args.mode, args.role), indent=2))
            else:
                print('Battle-Answer chat. Enter /quit to exit. Tools use the configured session copy.')
                while True:
                    try:
                        task = input('You> ')
                    except EOFError:
                        break
                    if task.strip() == '/quit':
                        break
                    if task.strip():
                        print(session.ask(task, args.mode, args.role)['answer'])
            return 0
        if args.command == 'run':
            task = Path(args.task_file).read_text() if args.task_file else args.task
            baseline = Path(args.baseline_file).read_text() if args.baseline_file else None
            estimate = plan(config, baseline is not None)
            if estimate['minimum_requests_new_run'] > config.max_calls:
                raise ArenaError('max_calls is below the tournament minimum. Reduce agents/votes or raise the explicit budget.')
            print(json.dumps(estimate, indent=2), flush=True)
            directory = args.dir or str(Path('.arena') / ('run-' + str(time.time_ns())))
            create_run(directory, task, config, args.workspace, baseline, args.seed, args.allow_exec,
                       args.allow_browser, args.allow_mcp)
        else:
            directory = args.dir
        from .assistant import terminal_approval
        report = Runner(directory, config, approve=terminal_approval).drive()
        print(json.dumps(report, indent=2))
        return 0
    except (ArenaError, OSError, ValueError) as exc:
        print('Arena stopped: ' + str(exc), file=sys.stderr)
        print('Completed checkpoints are retained. Fix configuration/budget or resume the same run.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted. Completed jobs are retained; use arena resume --dir <run>.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
