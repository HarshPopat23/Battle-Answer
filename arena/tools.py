"""Workspace-scoped tools; generated commands run only in opt-in Docker containers."""

import ipaddress
import http.client
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
from urllib import parse, request

from .config import ArenaError
from .providers import NoRedirect

MAX_FILE = 128 * 1024
MAX_OUTPUT = 16000
SKIP = {".git", ".arena", ".venv", "venv", "node_modules", "__pycache__", ".ssh", ".aws", ".gnupg", ".kube"}


def excluded(name):
    name = name.lower()
    return (name in SKIP or name == ".env" or name.startswith(".env.") or
            name.endswith((".pem", ".key", ".p12", ".pfx")) or
            "credential" in name or "secret" in name or name in {"id_rsa", "id_ed25519"})


def files(root):
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not excluded(d) and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            if not excluded(name) and not path.is_symlink() and path.is_file():
                yield path


def snapshot(source, target):
    """Copy a bounded, filtered project tree without following symlinks."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if not source.is_dir():
        raise ArenaError("workspace must be a directory.")
    count, total = 0, 0
    for path in files(source):
        # A run may live inside the supplied workspace, including at a custom path.
        if target == path or target in path.parents:
            continue
        size = path.stat().st_size
        count += 1
        total += size
        if count > 3000 or total > 32 * 1024 * 1024:
            raise ArenaError("Workspace snapshot exceeds 3000 files / 32 MiB. Select a smaller project directory.")
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    target.mkdir(parents=True, exist_ok=True)


SCHEMAS = {
    "list_files": {"path": "relative directory; default ."},
    "read_file": {"path": "relative UTF-8 text file (128 KiB maximum)"},
    "search_text": {"query": "literal text to find", "path": "relative directory; default ."},
    "write_file": {"path": "relative output file", "content": "complete UTF-8 file contents"},
    "run_command": {"argv": ["executable inside container", "argument"]},
    "fetch_url": {"url": "HTTPS URL on an explicitly allowed host; redirects forbidden"},
}


class Tools:
    def __init__(self, workspace, config, allow_exec=False, read_only=False):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.allow_exec = allow_exec
        self.read_only = read_only

    def available(self):
        names = ["list_files", "read_file", "search_text"]
        if not self.read_only:
            names.append("write_file")
            if self.allow_exec:
                names.append("run_command")
        if self.config.web_hosts:
            names.append("fetch_url")
        return {name: SCHEMAS[name] for name in names}

    def resolve(self, name):
        if not isinstance(name, str) or not name:
            raise ArenaError("Tool path must be a nonempty relative string.")
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or any(excluded(p) for p in path.parts):
            raise ArenaError("Path is outside the permitted project tree or is excluded.")
        current = self.root
        for part in path.parts:
            current /= part
            if current.is_symlink():
                raise ArenaError("Symlink paths are not accessible.")
        resolved = current.resolve()
        if not resolved.is_relative_to(self.root):
            raise ArenaError("Path escapes workspace.")
        return resolved

    def call(self, name, args):
        if name not in self.available():
            raise ArenaError("Tool is disabled or unknown: " + name)
        allowed = set(SCHEMAS[name])
        if set(args) - allowed:
            raise ArenaError("Unknown tool arguments.")
        try:
            result = getattr(self, name)(**args)
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            raise ArenaError("Tool failed: " + type(exc).__name__) from None
        return result

    def list_files(self, path="."):
        base = self.resolve(path)
        if not base.is_dir():
            raise ArenaError("Expected a directory.")
        result = []
        for file in files(base):
            result.append(file.relative_to(self.root).as_posix())
            if len(result) == 300:
                return {"files": result, "truncated": True}
        return {"files": result, "truncated": False}

    def read_file(self, path):
        file = self.resolve(path)
        if file.stat().st_size > MAX_FILE:
            raise ArenaError("File exceeds 128 KiB; select a smaller file.")
        return {"path": path, "content": file.read_text(encoding="utf-8")}

    def search_text(self, query, path="."):
        if not isinstance(query, str) or not query or len(query) > 1000:
            raise ArenaError("query must contain 1-1000 characters.")
        result = []
        base = self.resolve(path)
        if not base.is_dir():
            raise ArenaError("Expected a directory.")
        for index, file in enumerate(files(base)):
            if index >= 3000:
                break
            if file.stat().st_size > MAX_FILE:
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            for line, value in enumerate(text.splitlines(), 1):
                if query in value:
                    result.append({"path": file.relative_to(self.root).as_posix(), "line": line, "text": value[:300]})
                    if len(result) >= 40:
                        return {"matches": result, "truncated": True}
        return {"matches": result, "truncated": False}

    def write_file(self, path, content):
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE:
            raise ArenaError("content must be text of at most 128 KiB.")
        file = self.resolve(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return {"path": path, "bytes": len(content.encode("utf-8"))}

    def run_command(self, argv):
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 64 or
                not all(isinstance(x, str) and "\0" not in x and len(x) <= 4096 for x in argv)):
            raise ArenaError("argv must be a list of 1-64 command strings.")
        if not shutil.which("docker"):
            raise ArenaError("Docker is required for command execution; host shell execution is not supported.")
        if "," in str(self.root):
            raise ArenaError("Docker workspace paths cannot contain commas.")
        with tempfile.TemporaryDirectory(prefix="arena-container-") as temp:
            cid = Path(temp) / "cid"
            command = ["docker", "run", "--rm", "--pull=never", "--cidfile", str(cid),
                       "--network=none", "--log-driver=none", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--pids-limit=128", "--memory=512m", "--cpus=1", "--read-only",
                       "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--workdir", "/workspace",
                       "--mount", f"type=bind,src={self.root},dst=/workspace"]
            if hasattr(os, "getuid"):
                command += ["--user", f"{os.getuid()}:{os.getgid()}"]
            command += [self.config.docker_image, *argv]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            data = bytearray()

            def drain():
                while chunk := process.stdout.read(4096):
                    # Drain continuously without retaining unbounded RAM or disk logs.
                    if len(data) <= MAX_OUTPUT:
                        data.extend(chunk[:MAX_OUTPUT + 1 - len(data)])

            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            try:
                status = process.wait(timeout=self.config.command_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                status = None
            finally:
                if cid.exists():
                    container = cid.read_text().strip()
                    if len(container) == 64 and all(c in "0123456789abcdef" for c in container):
                        subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15, check=False)
                reader.join(timeout=5)
                process.stdout.close()
            return {"exit_code": status, "timed_out": status is None,
                    "output": data[:MAX_OUTPUT].decode("utf-8", errors="replace"),
                    "truncated": len(data) > MAX_OUTPUT}

    def fetch_url(self, url):
        if not isinstance(url, str):
            raise ArenaError("url must be a string.")
        parts = parse.urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in self.config.web_hosts or
                parts.username or parts.password or parts.port not in (None, 443)):
            raise ArenaError("URL must use HTTPS on an explicitly allowed web_hosts entry.")
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ArenaError("Web host must resolve to public addresses.")
        # Pin a validated public address for this connection, keeping TLS SNI and
        # certificate validation tied to the requested hostname (no second DNS lookup).
        class PinnedHTTPS(http.client.HTTPSConnection):
            def connect(self):
                address = addresses[0][4][0]
                self.sock = socket.create_connection((address, 443), self.timeout)
                self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)

        class Handler(request.HTTPSHandler):
            def https_open(self, req):
                return self.do_open(PinnedHTTPS, req, context=ssl.create_default_context())

        opener = request.build_opener(request.ProxyHandler({}), NoRedirect(), Handler())
        with opener.open(request.Request(url, headers={"User-Agent": "arena-standalone/0.2"}), timeout=20) as response:
            if response.headers.get_content_type() not in ("text/html", "text/plain", "application/json", "text/markdown"):
                raise ArenaError("Only text, HTML, JSON, and Markdown responses are supported.")
            data = response.read(MAX_OUTPUT + 1)
        return {"url": url, "content": data[:MAX_OUTPUT].decode("utf-8", errors="replace"),
                "truncated": len(data) > MAX_OUTPUT}
