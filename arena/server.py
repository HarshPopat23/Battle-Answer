"""Loopback-only chat UI with CSRF/origin checks and per-action approval handoff."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import unquote

from .assistant import AssistantSession
from .config import ArenaError


class ChatState:
    def __init__(self, config, directory, settings, session_factory=AssistantSession):
        self.config, self.directory, self.settings = config, Path(directory).resolve(), settings
        self.session_factory = session_factory
        self.lock = threading.Lock()
        self.approval_lock = threading.Lock()
        self.running = False
        self.answer = None
        self.error = None
        self.events = []
        self.pending = None
        self.decision = threading.Event()
        self.approved = False

    def event(self, value):
        with self.lock:
            self.events.append({**value, 'time': time.time()})
            self.events = self.events[-100:]

    def approve(self, name, args):
        # Tournament workers may request actions concurrently. Present one at a time.
        with self.approval_lock:
            with self.lock:
                self.approved = False
                self.pending = {'id': secrets.token_hex(12), 'tool': name, 'arguments': args}
                self.decision.clear()
            self.decision.wait(timeout=180)
            with self.lock:
                allowed = self.approved
                self.pending = None
                return allowed

    def start(self, task, mode, role):
        if not isinstance(task, str) or not task.strip() or len(task) > 30000:
            raise ArenaError('Task must contain 1-30000 characters.')
        if mode not in ('auto', 'single', 'arena') or role not in ('general', 'coder', 'researcher', 'reviewer'):
            raise ArenaError('Invalid mode or role.')
        with self.lock:
            if self.running:
                raise ArenaError('A task is already running.')
            self.running, self.answer, self.error, self.events = True, None, None, []

        def work():
            try:
                session = self.session_factory(self.directory, self.config, **self.settings,
                                               approve=self.approve, on_event=self.event)
                answer = session.ask(task, mode, role)
                with self.lock:
                    self.answer = answer
            except Exception as exc:
                with self.lock:
                    self.error = str(exc) if isinstance(exc, ArenaError) else 'Task failed; inspect the local session logs.'
            finally:
                with self.lock:
                    self.running = False

        threading.Thread(target=work, daemon=True).start()

    def view(self):
        with self.lock:
            artifacts = self.directory / 'artifacts'
            return {'running': self.running, 'answer': self.answer, 'error': self.error,
                    'events': list(self.events), 'approval': self.pending,
                    'screenshots': sorted(p.name for p in artifacts.glob('browser-*.png'))[-10:]}


def make_server(config, directory, settings, port=8765, session_factory=AssistantSession):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ArenaError('Port must be between 0 and 65535.')
    token = secrets.token_hex(32)
    state = ChatState(config, directory, settings, session_factory)
    template = (Path(__file__).parent / 'web' / 'chat.html').read_text(encoding='utf-8')

    class Handler(BaseHTTPRequestHandler):
        def permitted(self, mutate=False):
            host = self.headers.get('Host', '')
            allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if host not in allowed:
                return False
            source = self.headers.get('Origin')
            if source and source != 'http://' + host:
                return False
            if mutate and (self.headers.get('X-Arena-Token') != token or self.headers.get('Content-Type') != 'application/json'):
                return False
            return True

        def send(self, status, body, mime='application/json'):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', f"default-src 'self'; script-src 'nonce-{token}'; style-src 'nonce-{token}'; img-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.permitted():
                return self.send(403, {'error': 'Host/origin rejected'})
            if self.path == '/':
                return self.send(200, template.replace('__TOKEN__', token).encode(), 'text/html; charset=utf-8')
            if self.path == '/api/state':
                return self.send(200, state.view())
            if self.path.startswith('/artifacts/'):
                name = unquote(self.path[len('/artifacts/'):])
                root = state.directory / 'artifacts'
                file = root / name
                if name.startswith('browser-') and name.endswith('.png') and file.resolve().parent == root.resolve() and file.is_file() and not file.is_symlink():
                    return self.send(200, file.read_bytes(), 'image/png')
            return self.send(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.permitted(mutate=True):
                return self.send(403, {'error': 'CSRF/host/origin rejected'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 128000:
                    return self.send(413, {'error': 'Body must contain 1-128000 bytes'})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError()
                if self.path == '/api/ask':
                    state.start(body.get('task'), body.get('mode', 'auto'), body.get('role', 'general'))
                    return self.send(202, {'started': True})
                if self.path == '/api/approve':
                    with state.lock:
                        if not state.pending or state.decision.is_set() or body.get('id') != state.pending['id'] or type(body.get('allow')) is not bool:
                            raise ArenaError('No matching approval is pending.')
                        state.approved = body['allow']
                        state.decision.set()
                    return self.send(200, {'recorded': True})
                return self.send(404, {'error': 'Not found'})
            except (ValueError, TypeError, ArenaError) as exc:
                return self.send(400, {'error': str(exc) or 'Invalid request'})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.chat_state = state
    return server


def serve(config, directory, settings, port=8765):
    server = make_server(config, directory, settings, port)
    print(f'Battle-Answer: http://127.0.0.1:{server.server_port} (local access only)', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
