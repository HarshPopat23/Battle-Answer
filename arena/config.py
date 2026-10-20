"""Explicit provider settings; credentials are environment references, never config values."""

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit


class ArenaError(Exception):
    """An actionable failure that must stop or pause a run."""


PROVIDERS = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", ""),
    "openai-compatible": ("", "ARENA_API_KEY"),
    "anthropic": ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta", "GEMINI_API_KEY"),
}


@dataclass(frozen=True)
class Browser:
    enabled: bool = False
    origins: tuple[str, ...] = ()
    headless: bool = True
    executable_path: str = ""
    timeout_ms: int = 15000

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.headless) is not bool:
            raise ArenaError("browser enabled/headless must be booleans.")
        integer(self.timeout_ms, "browser.timeout_ms", 1000, 60000)
        if not isinstance(self.executable_path, str):
            raise ArenaError("browser.executable_path must be a string.")
        if not isinstance(self.origins, (tuple, list)):
            raise ArenaError("browser.origins must be an array.")
        for origin in self.origins:
            parts = urlsplit(origin)
            if (parts.scheme not in ("http", "https") or not parts.hostname or parts.path not in ("", "/")
                    or parts.username or parts.password or parts.query or parts.fragment
                    or not re.fullmatch(r"[A-Za-z0-9.:-]+", parts.hostname)):
                raise ArenaError("browser.origins must be exact HTTP(S) origins without paths or credentials.")
            try:
                parts.port
            except ValueError:
                raise ArenaError("Invalid browser origin port.") from None
            if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ArenaError("Browser HTTP origins are restricted to explicitly configured loopback services.")


@dataclass(frozen=True)
class MCPServer:
    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    read_tools: tuple[str, ...] = ()
    write_tools: tuple[str, ...] = ()
    timeout: int = 30

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", self.name):
            raise ArenaError("MCP server name must use lowercase letters, numbers, and underscores.")
        if bool(self.command) == bool(self.url):
            raise ArenaError("An MCP server needs exactly one of command or url.")
        if not isinstance(self.command, str):
            raise ArenaError("MCP command must be an executable string, not a shell command array.")
        if self.url:
            p = urlsplit(self.url)
            if (p.scheme not in ("https", "http") or not p.hostname or p.username or p.password or p.fragment or p.query
                    or (p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1", "::1"))):
                raise ArenaError("MCP URL must use HTTPS or explicitly configured loopback HTTP.")
        for field in ("args", "read_tools", "write_tools"):
            value = getattr(self, field)
            if not isinstance(value, (tuple, list)) or not all(isinstance(x, str) and x and '\0' not in x for x in value):
                raise ArenaError("MCP " + field + " must be an array of nonempty strings.")
        if set(self.read_tools) & set(self.write_tools):
            raise ArenaError("MCP read_tools and write_tools must not overlap.")
        if len(self.read_tools) + len(self.write_tools) > 32:
            raise ArenaError("At most 32 tools may be enabled per MCP server.")
        for values in (self.env, self.headers):
            if values is not None and (not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items())):
                raise ArenaError("MCP env/headers must map names to environment-variable references.")
            if values is not None and any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) for v in values.values()):
                raise ArenaError("MCP env/header values must name environment variables, not contain credentials.")
        integer(self.timeout, "MCP timeout", 1, 120)


@dataclass(frozen=True)
class Model:
    provider: str
    model: str
    api_base: str = ""
    api_key_env: str | None = None
    max_output_tokens: int = 4096
    timeout: float = 90
    retries: int = 2
    temperature: float | None = None
    token_parameter: str = ""

    def __post_init__(self):
        if self.provider not in PROVIDERS:
            raise ArenaError("Unknown provider. Choose: " + ", ".join(PROVIDERS))
        if not isinstance(self.model, str) or not self.model.strip():
            raise ArenaError("Set an explicit model ID from your provider's model list.")
        if not isinstance(self.api_base, str):
            raise ArenaError("api_base must be a URL string.")
        if not self.api_base:
            object.__setattr__(self, "api_base", PROVIDERS[self.provider][0])
        base = urlsplit(self.api_base)
        if (base.scheme not in ("http", "https") or not base.hostname or base.username
                or base.password or base.query or base.fragment):
            raise ArenaError("api_base must be an HTTP(S) URL without credentials, query, or fragment.")
        if base.scheme == "http" and base.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ArenaError("Remote provider endpoints require HTTPS; HTTP is allowed only on loopback.")
        if self.api_key_env is None:
            object.__setattr__(self, "api_key_env", PROVIDERS[self.provider][1])
        if not isinstance(self.api_key_env, str) or (self.api_key_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env)):
            raise ArenaError("api_key_env must name an environment variable, not contain a key.")
        integer(self.max_output_tokens, "max_output_tokens", 64, 131072)
        integer(self.retries, "retries", 0, 5)
        number(self.timeout, "timeout", 1, 600)
        if self.temperature is not None:
            number(self.temperature, "temperature", 0, 2)
        if self.token_parameter not in ("", "max_tokens", "max_completion_tokens"):
            raise ArenaError("token_parameter must be max_tokens or max_completion_tokens.")


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ArenaError(f"{name} must be an integer between {low} and {high}.")


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ArenaError(f"{name} must be a finite number between {low} and {high}.")


@dataclass(frozen=True)
class Config:
    worker: Model
    judge: Model
    fallback: Model | None = None
    agents: int = 4
    concurrency: int = 2
    judge_votes: int = 2
    repair_attempts: int = 2
    max_calls: int = 200
    max_total_tokens: int = 500000
    max_prompt_chars: int = 120000
    max_tool_steps: int = 8
    docker_image: str = "python:3.12-slim"
    command_timeout: int = 30
    web_hosts: tuple[str, ...] = ()
    verify_argv: tuple[str, ...] = ()
    browser: Browser = Browser()
    mcp_servers: tuple[MCPServer, ...] = ()

    def __post_init__(self):
        for name, lo, hi in [("agents", 1, 144), ("concurrency", 1, 32), ("judge_votes", 1, 2),
                             ("repair_attempts", 0, 3), ("max_calls", 1, 100000),
                             ("max_total_tokens", 1, 1000000000), ("max_prompt_chars", 1000, 1000000),
                             ("max_tool_steps", 0, 50), ("command_timeout", 1, 120)]:
            integer(getattr(self, name), name, lo, hi)
        if not isinstance(self.docker_image, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]*", self.docker_image):
            raise ArenaError("docker_image must be a Docker image reference.")
        if not isinstance(self.web_hosts, (tuple, list)) or not all(isinstance(h, str) and re.fullmatch(r"[A-Za-z0-9.-]+", h) for h in self.web_hosts):
            raise ArenaError("web_hosts must contain exact hostnames, without URLs or wildcards.")
        if not isinstance(self.verify_argv, (tuple, list)) or not all(isinstance(x, str) and x and '\0' not in x for x in self.verify_argv):
            raise ArenaError("verify_argv must be a list of command arguments.")
        if len(self.mcp_servers) > 8 or len({s.name for s in self.mcp_servers}) != len(self.mcp_servers):
            raise ArenaError("Configure at most eight MCP servers, with unique names.")

    def public(self):
        return asdict(self)


def load(path):
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        browser = Browser(**raw.pop("browser", {}))
        servers = tuple(MCPServer(**server) for server in raw.pop("mcp_servers", []))
        models = {role: Model(**raw.pop(role)) for role in ("worker", "judge", "fallback") if role in raw}
        if "worker" not in models:
            raise ArenaError("Configuration needs a [worker] table.")
        models.setdefault("judge", models["worker"])
        settings = raw.pop("arena", {})
        if raw:
            raise ArenaError("Unknown config sections: " + ", ".join(raw))
        for field in ("web_hosts", "verify_argv"):
            if field in settings:
                if not isinstance(settings[field], list):
                    raise ArenaError(field + " must be a TOML array.")
                settings[field] = tuple(settings[field])
        return Config(**models, **settings, browser=browser, mcp_servers=servers)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise ArenaError("Cannot load config: " + str(exc)) from None
