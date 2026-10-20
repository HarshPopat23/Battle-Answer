"""Isolated Playwright sessions with exact-origin network policy and action approval."""

from collections import deque
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from .config import ArenaError


def origin(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ArenaError('Browser accepts only HTTP(S) URLs without embedded credentials.')
    port = p.port or (443 if p.scheme == 'https' else 80)
    return p.scheme, p.hostname.lower(), port


SCHEMAS = {
    'browser_navigate': {'url': 'URL on a configured exact origin'},
    'browser_snapshot': {},
    'browser_click': {'ref': 'element reference from the latest snapshot'},
    'browser_fill': {'ref': 'element reference', 'text': 'text to type'},
    'browser_press': {'key': 'Enter, Tab, Escape, ArrowDown, or ArrowUp'},
    'browser_screenshot': {},
    'browser_tabs': {},
    'browser_switch_tab': {'index': 'integer tab index from browser_tabs'},
    'browser_evidence': {},
}


class BrowserSession:
    def __init__(self, settings, artifacts, approve=None):
        self.settings = settings
        self.artifacts = Path(artifacts)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.allowed = {origin(url) for url in settings.origins}
        if not self.allowed:
            raise ArenaError('Configure browser.origins before enabling the browser.')
        self.approve = approve
        self.network = deque(maxlen=100)
        self.console = deque(maxlen=50)
        self.mutations_until = 0
        self.playwright = self.browser = self.context = self.page = None

    def start(self):
        if self.page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ArenaError('Install the browser extra: pip install -e ".[browser]", then python -m playwright install chromium.') from None
        try:
            self.playwright = sync_playwright().start()
            kwargs = {'headless': self.settings.headless}
            if self.settings.executable_path:
                kwargs['executable_path'] = self.settings.executable_path
            self.browser = self.playwright.chromium.launch(**kwargs)
            self.context = self.browser.new_context(service_workers='block', accept_downloads=False)
            self.context.set_default_timeout(self.settings.timeout_ms)
            self.context.route('**/*', self.route)
            self.context.route_web_socket('**/*', lambda ws: ws.close())
            self.context.on('page', self.track_page)
            self.page = self.context.new_page()
        except Exception:
            self.close()
            raise ArenaError('Browser failed to start. Install Chromium/dependencies or configure browser.executable_path.') from None

    def track_page(self, page):
        if len(self.context.pages) > 4:
            page.close()
            return
        page.on('console', lambda msg: self.console.append({'type': msg.type, 'text': msg.text[:1000]}))
        page.on('pageerror', lambda exc: self.console.append({'type': 'error', 'text': str(exc)[:1000]}))
        page.on('response', lambda response: self.network.append({'method': response.request.method,
                    'url': response.url[:2000], 'status': response.status}))
        page.on('download', lambda download: download.cancel())

    def route(self, route):
        req = route.request
        try:
            if origin(req.url) not in self.allowed:
                raise ArenaError('origin blocked')
            if req.method not in ('GET', 'HEAD', 'OPTIONS') and time.monotonic() > self.mutations_until:
                raise ArenaError('unapproved write request blocked')
            # Chromium's route hook does not re-run for every redirected hop.
            # Fetch exactly one hop and fulfill it, rejecting redirects before
            # the browser can contact a second (possibly unapproved) origin.
            response = route.fetch(max_redirects=0, max_retries=0, timeout=self.settings.timeout_ms)
            try:
                if 300 <= response.status < 400:
                    self.network.append({'method': req.method, 'url': req.url[:2000], 'status': response.status, 'blocked': 'redirect'})
                    route.abort()
                else:
                    route.fulfill(response=response)
            finally:
                response.dispose()
        except Exception:
            route.abort()

    def call(self, name, args):
        if name not in SCHEMAS or set(args) != set(SCHEMAS[name]):
            raise ArenaError('Browser arguments do not match the tool schema.')
        self.start()
        try:
            if name in ('browser_click', 'browser_fill', 'browser_press'):
                if self.approve is None or not self.approve(name, args):
                    raise ArenaError('Browser interaction requires explicit approval; no action was performed.')
                self.mutations_until = time.monotonic() + self.settings.timeout_ms / 1000
            return getattr(self, name)(**args)
        except ArenaError:
            raise
        except Exception:
            raise ArenaError('Browser operation failed or timed out. Inspect browser_snapshot/browser_evidence and retry deliberately.') from None
        finally:
            # A later page timer does not inherit permission from an earlier click.
            self.mutations_until = 0

    def browser_navigate(self, url):
        if origin(url) not in self.allowed:
            raise ArenaError('Navigation origin is not explicitly allowed.')
        self.page.goto(url, wait_until='domcontentloaded')
        return self.browser_snapshot()

    def browser_snapshot(self):
        if self.page.url != 'about:blank' and origin(self.page.url) not in self.allowed:
            raise ArenaError('Page left the permitted origin.')
        elements = self.page.locator('a,button,input,textarea,select,[role=button]').evaluate_all('''nodes => nodes.slice(0,120).map((node,i) => {
          const ref = 'e' + i; node.setAttribute('data-arena-ref',ref);
          return {ref,tag:node.tagName.toLowerCase(),type:node.getAttribute('type'),
            label:(node.getAttribute('aria-label') || node.innerText || node.getAttribute('placeholder') || node.getAttribute('name') || '').slice(0,200)};
        })''')
        text = self.page.locator('body').inner_text() if self.page.locator('body').count() else ''
        return {'url': self.page.url, 'title': self.page.title(), 'text': text[:16000],
                'truncated': len(text) > 16000, 'elements': elements}

    def element(self, ref):
        if not isinstance(ref, str) or not re.fullmatch(r'e[0-9]{1,3}', ref):
            raise ArenaError('Use a reference from the latest browser snapshot.')
        return self.page.locator('[data-arena-ref="' + ref + '"]')

    def browser_click(self, ref):
        self.element(ref).click()
        return self.browser_snapshot()

    def browser_fill(self, ref, text):
        if not isinstance(text, str) or len(text) > 16000:
            raise ArenaError('Browser text must contain at most 16000 characters.')
        self.element(ref).fill(text)
        return self.browser_snapshot()

    def browser_press(self, key):
        if key not in ('Enter', 'Tab', 'Escape', 'ArrowDown', 'ArrowUp'):
            raise ArenaError('Unsupported browser key.')
        self.page.keyboard.press(key)
        return self.browser_snapshot()

    def browser_screenshot(self):
        name = 'browser-' + str(time.time_ns()) + '.png'
        self.page.screenshot(path=str(self.artifacts / name), full_page=False)
        return {'artifact': name, 'url': self.page.url, 'note': 'Saved for user inspection; text-only model adapters do not see pixels.'}

    def browser_tabs(self):
        return {'tabs': [{'index': i, 'url': page.url} for i, page in enumerate(self.context.pages)]}

    def browser_switch_tab(self, index):
        if type(index) is not int or not 0 <= index < len(self.context.pages):
            raise ArenaError('Unknown tab index.')
        self.page = self.context.pages[index]
        return self.browser_snapshot()

    def browser_evidence(self):
        return {'console': list(self.console), 'network': list(self.network)}

    def close(self):
        for resource, method in ((self.context, 'close'), (self.browser, 'close'), (self.playwright, 'stop')):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass
        self.playwright = self.browser = self.context = self.page = None
