"""Small REST adapters. No provider SDK, native tool-calling, or Claude Code required."""

from dataclasses import dataclass
import json
import os
import socket
import time
from urllib import error, parse, request

from .config import ArenaError, Model


class ProviderError(ArenaError):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class Reply:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def _usage(raw, key):
    value = raw.get(key)
    return value if type(value) is int and value >= 0 else None


class Client:
    def __init__(self, model: Model):
        self.model = model
        self.opener = request.build_opener(NoRedirect())

    def credentials(self):
        env = self.model.api_key_env
        key = os.environ.get(env, "") if env else ""
        if env and not key:
            raise ProviderError(f"Set the {env} environment variable for {self.model.provider}.")
        return key

    def payload(self, messages):
        m = self.model
        base = m.api_base.rstrip("/")
        key = self.credentials()
        headers = {"Content-Type": "application/json", "User-Agent": "arena-standalone/0.2"}
        if m.provider == "anthropic":
            url = base + "/messages"
            headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
            body = {"model": m.model, "max_tokens": m.max_output_tokens,
                    "system": "\n\n".join(x["content"] for x in messages if x["role"] == "system"),
                    "messages": [x for x in messages if x["role"] != "system"]}
        elif m.provider == "gemini":
            url = base + "/models/" + parse.quote(m.model.removeprefix("models/"), safe="") + ":generateContent"
            headers["x-goog-api-key"] = key
            body = {
                "systemInstruction": {"parts": [{"text": "\n\n".join(x["content"] for x in messages if x["role"] == "system")}]},
                "contents": [{"role": "model" if x["role"] == "assistant" else "user", "parts": [{"text": x["content"]}]}
                             for x in messages if x["role"] != "system"],
                "generationConfig": {"maxOutputTokens": m.max_output_tokens},
            }
        else:
            url = base + "/chat/completions"
            if key:
                headers["Authorization"] = "Bearer " + key
            token_key = m.token_parameter or ("max_completion_tokens" if m.provider in ("openai", "groq") else "max_tokens")
            body = {"model": m.model, "messages": messages, token_key: m.max_output_tokens}
        if m.temperature is not None:
            target = body["generationConfig"] if m.provider == "gemini" else body
            target["temperature"] = m.temperature
        return url, headers, body

    def generate(self, messages, before_request=lambda: None):
        url, headers, body = self.payload(messages)
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        for attempt in range(self.model.retries + 1):
            before_request()  # Counts retries against the run's request budget too.
            retry_after = None
            try:
                req = request.Request(url, data=raw, headers=headers, method="POST")
                with self.opener.open(req, timeout=self.model.timeout) as response:
                    content = response.read(8 * 1024 * 1024 + 1)
                if len(content) > 8 * 1024 * 1024:
                    raise ProviderError("Provider response exceeds the 8 MiB limit.")
                return self.decode(json.loads(content))
            except error.HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After") or exc.headers.get("retry-after")
                reset_tokens = exc.headers.get("x-ratelimit-reset-tokens") or exc.headers.get("x-ratelimit-reset-requests")
                if not retry_after and reset_tokens:
                    try:
                        s = str(reset_tokens).strip()
                        if s.endswith("ms"):
                            retry_after = float(s[:-2]) / 1000.0 + 0.5
                        elif s.endswith("s"):
                            retry_after = float(s[:-1]) + 0.5
                        elif s.endswith("m"):
                            retry_after = float(s[:-1]) * 60.0 + 0.5
                    except Exception:
                        pass
                exc.close()
                if status not in (429, 500, 502, 503, 504) or attempt == self.model.retries:
                    # Do not echo provider bodies/URLs that may contain secrets or task data.
                    raise ProviderError(f"{self.model.provider} returned HTTP {status}; check model, credentials, quota, and endpoint.") from None
            except (error.URLError, TimeoutError, socket.timeout):
                if attempt == self.model.retries:
                    raise ProviderError(f"{self.model.provider} connection failed or timed out.") from None
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError, IndexError, TypeError, AttributeError):
                raise ProviderError(f"{self.model.provider} returned an invalid or unsupported response shape.") from None
            try:
                delay = min(60, max(1.0, float(retry_after))) if retry_after else min(20, 2 ** (attempt + 1) + 2)
            except (ValueError, TypeError):
                delay = min(20, 2 ** (attempt + 1) + 2)
            time.sleep(delay)
        raise ProviderError("Provider retry limit reached.")

    def decode(self, data):
        if self.model.provider == "anthropic":
            if data.get("stop_reason") not in ("end_turn", "stop_sequence"):
                raise ProviderError("Anthropic response did not complete; increase output limit or choose a compatible model.")
            text = "\n".join(x["text"] for x in data["content"] if x.get("type") == "text")
            usage = data.get("usage", {})
            reply = Reply(text, _usage(usage, "input_tokens"), _usage(usage, "output_tokens"))
        elif self.model.provider == "gemini":
            item = data.get("candidates", [{}])[0]
            if item.get("finishReason") != "STOP":
                raise ProviderError("Gemini response was blocked, truncated, or incomplete; check model/output limit.")
            text = "\n".join(p["text"] for p in item["content"]["parts"] if "text" in p and not p.get("thought"))
            usage = data.get("usageMetadata", {})
            # totalTokenCount includes reasoning tokens on supporting models.
            inp = _usage(usage, "promptTokenCount")
            total = _usage(usage, "totalTokenCount")
            out = total - inp if total is not None and inp is not None and total >= inp else _usage(usage, "candidatesTokenCount")
            reply = Reply(text, inp, out)
        else:
            item = data["choices"][0]
            if item.get("finish_reason") != "stop":
                raise ProviderError("Model did not finish a text response; increase output limit or use a text-capable model.")
            text = item["message"].get("content")
            if isinstance(text, list):
                text = "\n".join(x["text"] for x in text if x.get("type") == "text")
            usage = data.get("usage", {})
            reply = Reply(text, _usage(usage, "prompt_tokens"), _usage(usage, "completion_tokens"))
        if not isinstance(reply.text, str) or not reply.text.strip():
            raise ProviderError("Model returned no usable text.")
        return reply
