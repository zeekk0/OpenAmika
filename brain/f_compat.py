"""An OpenAI-compatible chat server as a transport for the four Build F roles.

LM Studio, llama.cpp's server, vLLM, LocalAI, or a hosted API: whatever answers ``GET {base}/models`` and
``POST {base}/chat/completions``. ``config/openai_compat.json`` (git-ignored) holds the address and the models
found there; f_roles generates one option per model and role ("<role>:compat:<model>"). Receipts, metering and
the drain machinery are the OpenRouter client's.

Plain http is for local servers only: such an address must not be a public one, which is checked when it is saved
and again before every call (``local_address``), so a name that comes to stand for a public address is refused
too. A server outside your own network needs https.

The API key is optional. It lives in brain/.env (OPENAI_COMPAT_API_KEY) and is sent only to the address it was
entered for (``key_base_url``): pointing the page at another server, or naming another server in an entry, cannot
carry a saved key there. Redirects are never followed.

What these servers do not have in common, and how each is handled here:

- Thinking. A server may put it in a separate field (ignored: only ``delta.content`` is read), inline as a leading
  ``<think>…</think>``, or inline with the opening tag already in the prompt, so that only ``</think>`` arrives.
  ThinkFilter removes both inline forms before a word can reach her voice.
- Model names. llama.cpp answers with a file path, so a differing name is recorded and is not an error.
- Usage. Some servers report none: the call still counts as complete, with zero tokens.
- Cost. A server of your own charges nothing: the ledger books these calls at zero, as it does Ollama's. An https
  server that reports its charge in the usage object (reported_charge) is booked at it, cost source "provider";
  any other is booked at zero, "unreported". No price is known before a call, so the reservation is a placeholder.
- JSON mode. LM Studio refuses ``response_format: json_object``, so none is sent; the writer's prompt asks for JSON.
- Parameters. A 400 naming ``max_completion_tokens`` or ``stream_options`` adapts the request once and is
  remembered per server. A refused request generated nothing, so this is not a retry of a call that ran.
"""
import contextlib
import copy
import ipaddress
import itertools
import json
import math
import os
import re
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from f_memory import _write
from f_ollama import ANSWER_TOKENS
from f_openrouter import (MAX_OUTPUT_TOKENS, OpenRouterClient, OpenRouterError, ROLES, _merge, first_line,
                          normalize_usage)

COMPAT = "openai_compat"
CONFIG_NAME = "openai_compat.json"
KEY_ENV = "OPENAI_COMPAT_API_KEY"
DEFAULT_URL = "http://127.0.0.1:1234/v1"       # LM Studio's default; llama.cpp and vLLM differ only in the port
ADDRESS_NEEDED = "The server address must look like http://127.0.0.1:1234/v1 or https://host/v1, with no credentials"
USE_HTTPS = "plain http is for local servers only: use https for a server outside your own network"

_URL_RE = re.compile(r"^https?://[A-Za-z0-9._\-\[\]:]+(?:/[A-Za-z0-9._~\-]+)*$")
# A key is kept in brain/.env, which python-dotenv reads when the brain starts: it puts another variable's value in
# place of ${NAME}, and reads a leading quote as the start of a quoted value. A key with one of $ " ' ` \ # could
# come back from the file as something else, another provider's key included. Such a key is refused, like a space.
_KEY_RE = re.compile(r"""(?:(?!["#$'\\`])[\x21-\x7e]){1,1024}""")
KEY_REFUSED = ("That API key has a space or a character a key cannot contain here: $ # \" ' ` \\ or anything that is "
               "not plain ASCII.")
_NOT_CHAT_RE = re.compile(r"embed|whisper|tts|dall-e|moderation|rerank", re.I)
_OPEN_TAGS = ("<think>", "<thinking>", "<reasoning>")
_CLOSE_RE = re.compile(r"</(?:think|thinking|reasoning)>", re.I)
# How a real answer begins, per role whose text is spoken: reasoning that lacks its opening tag does not look like
# this and is held back until its closing tag. The other roles are not spoken, so all of their text can wait.
_SPOKEN_STARTS = {"surface": ("status",), "deep": ("[", "我说", "我接着说", "我心想")}
_QUIRKS = {}                                   # chat URL -> what its server refused (learned from a 400)
# The key is in brain/.env and the address it is bound to is in the config file, so the two cannot change in one
# step. Three things keep a key from being paired with the address another key was entered for:
# - save_key numbers each new key (_KEY_STAMP) and a config remembers the number it was read under, so a config
#   read before the key was replaced gets no key (saved_key);
# - the detect route takes the old key's address off the disk before it replaces the key, and binds the new address
#   after: a config read in between has no address in it;
# - one detect at a time reads the file, changes it and writes it back (_SAVING).
_KEY_CHANGES = itertools.count(1)
_KEY_STAMP = 0
_SAVING = threading.Lock()


def compat_base_url(url):
    """http(s)://host[:port][/path], no query or credentials. No path means /v1; a pasted endpoint is trimmed. A
    plain-http address that is a public one as written is refused here; a name is looked up by local_address()."""
    url = str(url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_URL
    url = re.sub(r"/(?:chat/completions|models)$", "", url)
    if not _URL_RE.match(url):
        raise ValueError(ADDRESS_NEEDED)
    parts = urlsplit(url)
    try:
        host, _ = parts.hostname, parts.port
    except ValueError:
        raise ValueError(ADDRESS_NEEDED) from None
    if not host:
        raise ValueError(ADDRESS_NEEDED)
    try:
        public = ipaddress.ip_address(host).is_global
    except ValueError:
        public = False          # a name: local_address() looks it up when it is saved and before it is used
    if public and parts.scheme != "https":
        raise ValueError(f"{host} is a public address; {USE_HTTPS}")
    return url if parts.path else url + "/v1"


def is_local(base_url):
    """True for a plain-http address: the kind that is only ever a server of the person's own."""
    return urlsplit(base_url).scheme == "http"


def local_address(base_url):
    """For a plain-http address: the addresses its name stands for right now, none of them on the public internet;
    ValueError otherwise. Asked when an address is saved and again before every call, because a name can change
    what it stands for. An https address may be anywhere and is not looked up: []."""
    parts = urlsplit(base_url)
    if parts.scheme == "https":
        return []
    host, port = parts.hostname or "", parts.port or 80
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise ValueError(f"{host} does not resolve: {error}") from None
    addresses = [info[4][0] for info in found]
    for address in addresses:
        if ipaddress.ip_address(address.split("%")[0]).is_global:
            raise ValueError(f"{host} is a public address ({address}); {USE_HTTPS}")
    return addresses


def _entry_options(row):
    """The optional per-entry fields present in a model row, validated; a ValueError says which one is wrong."""
    out = {}
    served = row.get("served_name")
    if served is not None:
        if not isinstance(served, str) or not served.strip() or len(served) > 200:
            raise ValueError("served_name must be the name the server knows the model by")
        out["served_name"] = served.strip()
    base = row.get("base_url")
    if base is not None:
        if not isinstance(base, str) or not base.strip():     # "" would otherwise silently mean the default server
            raise ValueError("base_url must be a server address")
        out["base_url"] = compat_base_url(base)
    kwargs = row.get("chat_template_kwargs")
    if kwargs is not None:
        if not isinstance(kwargs, dict):
            raise ValueError("chat_template_kwargs must be an object")
        if kwargs:
            out["chat_template_kwargs"] = kwargs
    thinking = row.get("thinking_tokens")
    if thinking is not None:
        if isinstance(thinking, bool) or not isinstance(thinking, int) or thinking < 0:
            raise ValueError("thinking_tokens must be a whole number of at least 0")
        out["thinking_tokens"] = thinking
    return out


def _model_row(row):
    name = row.get("name") if isinstance(row, dict) else None
    if not isinstance(name, str) or not name.strip() or len(name) > 200 or _NOT_CHAT_RE.search(name):
        return None
    try:
        return {"name": name.strip(), **_entry_options(row)}
    except ValueError as error:
        # Falling back to the main server would send this role somewhere the operator did not ask for.
        print(f"[compat] model entry {name!r} is not offered: {error}")
        return None


class _Read(dict):
    """The config as load_compat_config read it. key_stamp: the number of the key that was in force then."""


def load_compat_config(root):
    """config/openai_compat.json as the role manager uses it (defaults when the file is missing or odd)."""
    stamp = _KEY_STAMP          # taken before the file is read: what is read belongs to this key or to a later one
    path = Path(root) / "config" / CONFIG_NAME
    doc = {}
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError:
            doc = {}
    if not isinstance(doc, dict):
        doc = {}
    try:
        base = compat_base_url(doc.get("base_url"))
    except ValueError:
        base = DEFAULT_URL
    bound = doc.get("key_base_url")
    config = _Read({"base_url": base, "key_base_url": bound if isinstance(bound, str) else None,
                    "detected_at": doc.get("detected_at"),
                    "models": [m for m in (_model_row(r) for r in (doc.get("models") or [])) if m]})
    config.key_stamp = stamp
    return config


def save_compat_config(root, doc):
    _write(Path(root) / "config" / CONFIG_NAME, doc)


def saved_key(compat, base_url=None):
    """The key from brain/.env, only for the address it was entered for; "" for any other address. `compat` is the
    config as load_compat_config read it: one read before the key was last replaced gets "" too, because the
    address in it was bound to the key before and says nothing about this one."""
    bound = compat.get("key_base_url")
    if not bound or bound != (base_url or compat.get("base_url")):
        return ""
    key = os.getenv(KEY_ENV) or ""      # read before the numbers are compared: save_key changes the number first
    return key if getattr(compat, "key_stamp", _KEY_STAMP) == _KEY_STAMP else ""


def save_key(env_path, key):
    """Write the key into brain/.env, the file every other provider key lives in."""
    global _KEY_STAMP
    from f_persona import _write_atomic
    if not _KEY_RE.fullmatch(key):
        raise ValueError(KEY_REFUSED)       # the file's reader would not give it back as written
    env_path = Path(env_path)
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.is_file() else []
    entry = f"{KEY_ENV}={key}"
    for index, line in enumerate(lines):
        if line.strip().startswith(KEY_ENV + "="):
            lines[index] = entry
            break
    else:
        lines.append(entry)
    _write_atomic(env_path, "\n".join(lines) + "\n")
    _KEY_STAMP = next(_KEY_CHANGES)     # before the key itself: from here on a config read earlier gets no key
    os.environ[KEY_ENV] = key


def merged_models(current, detected):
    """A detect refreshes what the server lists; an entry written by hand (any field beyond its name) stays."""
    kept = [m for m in current if set(m) != {"name"}]
    names = {m["name"] for m in kept}
    return sorted(kept + [m for m in detected if m["name"] not in names], key=lambda m: m["name"])


def _error_detail(response, key=""):
    """The server's own explanation, closed and bounded, with the key removed should a server echo it."""
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            payload = payload[0]                 # Google's OpenAI-compatible endpoint wraps its error in a list
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            error = error.get("message")
        detail = str(error or (payload.get("detail") if isinstance(payload, dict) else "") or "")
    except Exception:
        pass
    try:
        response.close()
    except Exception:
        pass
    return (detail.replace(key, "…") if key else detail)[:240]


def discover(http, base_url, key="", *, timeout=(3, 15)):
    """The chat models this server lists: [{name}], sorted. Read-only; raises when it does not answer. `key` is
    the caller's to judge (saved_key): it is sent to this address as given."""
    base = compat_base_url(base_url)
    try:
        local_address(base)
    except ValueError as error:
        raise OpenRouterError(str(error)) from None
    headers = {"Authorization": "Bearer " + key} if key else {}
    response = http.get(base + "/models", headers=headers, timeout=timeout, allow_redirects=False)
    status = getattr(response, "status_code", 200)
    if status in (401, 403):
        _error_detail(response, key)
        raise OpenRouterError("the server refused the API key" if key else
                              "the server asks for an API key: enter it with the address")
    if status != 200:
        detail = _error_detail(response, key)
        raise OpenRouterError(f"HTTP {status}" + (f": {detail}" if detail else ""))
    try:
        payload = response.json()
    except ValueError:
        raise OpenRouterError("the answer is not JSON (is this the OpenAI-compatible address?)") from None
    finally:
        try:
            response.close()
        except Exception:
            pass
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise OpenRouterError("the answer has no model list (is this the OpenAI-compatible address?)")
    models = [m for m in (_model_row({"name": r.get("id")}) for r in rows if isinstance(r, dict)) if m]
    return sorted(models, key=lambda m: m["name"])


# xAI reports a call's charge in its usage object as an integer number of ticks: $1 is 10**10 ticks.
USD_TICKS = 10 ** 10


def reported_charge(usage):
    """The charge, in USD, that a hosted server put in a call's usage object, or None when it reported none.

    Two forms are known: xAI's ``cost_in_usd_ticks`` (an integer, 10**10 ticks to the dollar) and a plain ``cost``
    in dollars (OpenRouter's form). Anything else, a negative amount, a boolean or a number too large to be an
    amount is no report at all."""
    usage = usage if isinstance(usage, dict) else {}
    try:
        ticks = usage.get("cost_in_usd_ticks")
        if isinstance(ticks, int) and not isinstance(ticks, bool) and ticks >= 0:
            return ticks / USD_TICKS
        cost = usage.get("cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
            return float(cost)
    except OverflowError:       # an integer beyond a float's range, from a server nobody reviewed
        pass
    return None


def compat_role_config(compat, model_name, role, *, max_tokens=None):
    """Per-role parameters for a listed model (the shape the role manager and the client read)."""
    role = "memory_write" if role == "memory_extraction" else role
    entry = next((m for m in (compat.get("models") or []) if m["name"] == model_name), None)
    if role not in ROLES or not isinstance(model_name, str) or entry is None:
        raise ValueError("Unknown role, or this server does not list that model (detect models first)")
    answer = ANSWER_TOKENS[role] if max_tokens is None else max_tokens
    # a model that reasons first spends this before the answer budget starts
    thinking = entry.get("thinking_tokens", compat.get("thinking_tokens"))
    if isinstance(answer, int) and isinstance(thinking, int) and not isinstance(thinking, bool) and thinking > 0:
        answer = min(answer + thinking, MAX_OUTPUT_TOKENS)
    if isinstance(answer, bool) or not isinstance(answer, int) or not 1 <= answer <= MAX_OUTPUT_TOKENS:
        raise ValueError("max_tokens must be an integer between 1 and 8192")
    served = entry.get("served_name") or model_name
    options = {"chat_template_kwargs": copy.deepcopy(entry["chat_template_kwargs"])} if "chat_template_kwargs" in entry else {}
    return {**options, "transport": COMPAT, "model_id": model_name, "api_model": served, "canonical_slug": served,
            "provider_tag": COMPAT, "provider_name": "OpenAI-compatible server", "role": role, "max_tokens": answer,
            "reasoning": None, "reasoning_enabled": False, "mandatory_reasoning": False,
            "max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0}, "reservation_input_rate": 0.0,
            "base_url": entry.get("base_url") or compat.get("base_url") or DEFAULT_URL, "supported_parameters": [],
            "structured_outputs_advertised": False}


def make_compat_body(config, messages, *, stream=True):
    if config.get("transport") != COMPAT or config.get("role") not in ROLES or not config.get("api_model"):
        raise ValueError("Use a validated OpenAI-compatible role config")
    if not isinstance(messages, list) or not messages:
        raise ValueError("A nonempty message list is required")
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"}:
            raise ValueError("Only system, user, and assistant text messages are supported")
        if not isinstance(message.get("content"), str):
            raise ValueError("This transport accepts text-only messages")
    body = {"model": config["api_model"], "messages": copy.deepcopy(messages), "stream": bool(stream),
            "max_tokens": int(config["max_tokens"])}
    if stream:
        body["stream_options"] = {"include_usage": True}
    if config.get("chat_template_kwargs"):
        body["chat_template_kwargs"] = copy.deepcopy(config["chat_template_kwargs"])
    return body


def strip_thinking(text):
    """A whole reply without its thinking. JSON (the memory writer's) may quote anything, so it is left alone."""
    head = text.lstrip()
    if head.startswith(("{", "```")):
        return text
    match = _CLOSE_RE.search(text)
    if match:
        return text[match.end():].lstrip()
    return "" if head.lower().startswith(_OPEN_TAGS) else text


class ThinkFilter:
    """Streamed text in, spoken text out. Once the answer has begun every chunk passes through untouched."""

    def __init__(self, role):
        self.starts = _SPOKEN_STARTS.get(role, ())
        self.state = "start"          # start → thinking | held → trim → body; or start → body
        self.buffer = ""

    def feed(self, text, final=False):
        if self.state == "body":
            return text
        if self.state == "trim":
            text = text.lstrip()
            if text:
                self.state = "body"
            return text
        self.buffer += text
        out = self._advance()
        if final and self.state in ("start", "held"):
            # No closing tag ever came, so that was the answer, however odd it looked.
            out, self.buffer, self.state = self.buffer.lstrip(), "", "body"
        return out

    def _advance(self):
        if self.state == "start":
            head = self.buffer.lstrip()
            low = head.lower()
            if not head:
                return ""
            tag = next((t for t in _OPEN_TAGS if low.startswith(t)), None)
            if tag:
                self.buffer, self.state = head[len(tag):], "thinking"
            elif any(low.startswith(s) for s in self.starts):
                self.buffer, self.state = "", "body"
                return head
            elif any(t.startswith(low) for t in _OPEN_TAGS + self.starts):
                return ""             # still too short to tell
            else:
                self.state = "held"
        match = _CLOSE_RE.search(self.buffer)
        if not match:
            return ""
        rest, self.buffer = self.buffer[match.end():].lstrip(), ""
        self.state = "body" if rest else "trim"
        return rest


class CompatClient(OpenRouterClient):
    """OpenAI-style chat with the OpenRouter client's receipts, metering and drain."""
    transport = COMPAT
    provider_name = "Your model server"

    def __init__(self, http, before_call, after_call, *, base_url, api_key="", timeout=(10, 600), event_sink=None,
                 drainer=None):
        # The parent insists on a key. Most of these servers have none, and then no Authorization header is sent
        # (_post). The caller passes a key only for the address it was entered for (saved_key).
        super().__init__(http, api_key or "local", before_call, after_call, timeout=timeout, event_sink=event_sink,
                         drainer=drainer)
        self.api_key = api_key or ""
        self.base_url = compat_base_url(base_url)
        self.chat_url = self.base_url + "/chat/completions"

    def _chat_body(self, config, messages, *, stream, json_schema=None):
        return make_compat_body(config, messages, stream=stream)

    def _reservation(self, config, body):
        return 0.00001        # a positive reservation keeps the budget gate happy; the price is zero or unknown

    def _prepare(self, config, body, metadata, url):
        handle, receipt = super()._prepare(config, body, metadata, url)
        receipt["request_id"] = "compat-" + uuid.uuid4().hex[:12]     # telemetry keys its timings by id
        receipt["actual_provider"] = COMPAT
        receipt["_think"] = ThinkFilter(config["role"])
        # The reservation is a placeholder, not a bound on the price, so a charge the server reports afterwards is
        # not "more than was reserved" (f_openrouter's settle step reads this).
        receipt["reservation_is_placeholder"] = True
        return handle, receipt

    def _usage(self, receipt, embedding):
        raw = receipt.get("raw_usage") or {}
        counts = {k: raw[k] if isinstance(raw.get(k), int) and not isinstance(raw.get(k), bool) and raw[k] >= 0 else 0
                  for k in ("prompt_tokens", "completion_tokens")}
        local = is_local(self.base_url)
        charge = None if local else reported_charge(raw)
        receipt["raw_usage"] = dict(counts, cost=0.0 if charge is None else charge)
        usage = normalize_usage(receipt["raw_usage"], embedding=embedding)
        usage["cost_source"] = "local" if local else "unreported" if charge is None else "provider"
        return usage

    def _settle(self, handle, receipt, started, done, cancelled, error, *, embedding=False, drained=False):
        think = receipt.pop("_think", None)   # a filter is not JSON; the receipt is archived
        if done and not cancelled and think is not None and think.state == "thinking":
            receipt["reasoning_unfinished"] = True
            print(f"[compat] {receipt['requested_model']} used its whole answer budget thinking; she said nothing")
        super()._settle(handle, receipt, started, done, cancelled, error, embedding=embedding, drained=drained)

    def _adapt(self, body, url):
        quirks = _QUIRKS.get(url, ())
        if "max_completion_tokens" in quirks and "max_tokens" in body:
            body["max_completion_tokens"] = body.pop("max_tokens")
        if "no_stream_options" in quirks:
            body.pop("stream_options", None)

    def _told(self, error, words):
        """`error` with the line for the person on it (her chat log, a Discord reply: f_openrouter.describe_error).
        Its type and message stay as they are: memory jobs tell a failure that is worth retrying by them."""
        with contextlib.suppress(Exception):
            error.provider_detail = f"{self.provider_name}: {words}"
        return error

    def _post(self, url, body, stream):
        try:
            local_address(self.base_url)      # every call: the name may have come to stand for a public address
        except ValueError as error:
            raise self._told(OpenRouterError(str(error)), str(error)) from None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        for _ in range(3):
            self._adapt(body, url)
            try:
                response = self.http.post(url, headers=headers, json=body, stream=stream, timeout=self.timeout,
                                          allow_redirects=False)
            except Exception as error:
                kinds = {cls.__name__ for cls in type(error).__mro__}
                if "ReadTimeout" in kinds:
                    self._told(error, f"no answer from {self.base_url} in time; it may be loading the model")
                elif kinds & {"ConnectionError", "ConnectTimeout"}:
                    self._told(error, f"nothing answers at {self.base_url} — is it running?")
                raise
            status = getattr(response, "status_code", 200)
            if status < 300:
                return response
            detail = _error_detail(response, self.api_key)
            low = detail.lower()
            quirk = None
            if status in (400, 422) and "max_completion_tokens" in low and "max_tokens" in body:
                quirk = "max_completion_tokens"
            elif status in (400, 422) and "stream_options" in low and "stream_options" in body:
                quirk = "no_stream_options"
            if quirk is None:
                said = first_line(detail) or "no reason given"
                if status in (401, 403):
                    said = ("it refused the API key: enter a new one on Setup → Brain" if self.api_key else
                            "it asks for an API key: enter it on Setup → Brain")
                raise self._told(OpenRouterError(f"The server answered HTTP {status}" + (f": {detail}" if detail else "")),
                                 f"HTTP {status}: {said}")
            _QUIRKS.setdefault(url, set()).add(quirk)
        raise self._told(OpenRouterError("The server kept refusing the request's parameters"),
                         "it kept refusing the request's parameters")

    def _event(self, config, receipt, data):
        if not isinstance(data, dict):
            raise OpenRouterError("The server returned a non-object event")
        if data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else error
            if self.api_key and message is not None:
                message = str(message).replace(self.api_key, "…")    # a server that echoes the key, as in _error_detail
            raise self._told(OpenRouterError("The server reported an error: " + str(message)[:200]),
                             first_line(message) or "an error with no reason given")
        if data.get("model"):
            receipt["actual_model"] = str(data["model"])
        if isinstance(data.get("usage"), dict):
            _merge(receipt["raw_usage"], data["usage"])

    def _stream_line(self, config, receipt, line, started):
        """One SSE line: None = skip, True = [DONE], else the text she may use (never any thinking)."""
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line or not line.startswith("data:"):
            return None
        raw = line[5:].strip()
        if raw == "[DONE]":
            return True
        data = json.loads(raw)
        if receipt["timing"]["first_event_s"] is None:
            receipt["timing"]["first_event_s"] = time.perf_counter() - started
        self._event(config, receipt, data)
        choices = data.get("choices") or []
        if not choices:
            return ""
        choice = choices[0]
        finished = choice.get("finish_reason") is not None
        if finished:
            receipt["finish_reason"] = choice["finish_reason"]
            receipt["truncated"] = choice["finish_reason"] in {"length", "max_tokens"}
        text = (choice.get("delta") or {}).get("content")
        if text is not None and not isinstance(text, str):
            raise OpenRouterError("The server returned non-text content")
        visible = receipt["_think"].feed(text or "", final=finished)
        if visible:
            if receipt["timing"]["first_content_s"] is None:
                receipt["timing"]["first_content_s"] = time.perf_counter() - started
            receipt["content"] += visible
            if self.event_sink:
                self.event_sink({"id": receipt["request_id"], "model": receipt["actual_model"],
                                 "choices": [{"delta": {"content": visible}}]})
        return visible

    def complete(self, config, messages, *, metadata=None, json_schema=None):
        result = super().complete(config, messages, metadata=metadata, json_schema=json_schema)
        result["text"] = result["receipt"]["content"] = strip_thinking(result["text"])
        return result

    def embed(self, *args, **kwargs):
        raise ValueError("This transport serves chat roles only (embeddings run on the local bge-m3 server)")


# ------------------------------------------------------------------ brain routes
def install_compat(g):
    """GET /api/build_f/compat (address, models, is it up, is a key saved: never the key), POST …/compat/detect
    (probe an address, save config/openai_compat.json and a new key, refresh the role options), POST …/compat/use."""
    app, request, jsonify = g["app"], g["request"], g["jsonify"]
    root = Path(g["__file__"]).resolve().parent.parent

    def action_request(action):
        if request.headers.get("Origin") or request.headers.get("X-Build-F-Action") != action:
            raise PermissionError("Use the OpenAmika page for this action.")
        value = request.get_json(silent=True) if request.is_json else None
        if not isinstance(value, dict):
            raise ValueError("A JSON object is required.")
        return value

    def in_use(manager):
        if manager is None:
            return {}
        with manager.lock:
            return {role: manager.options[role][manager.selections[role]]["config"]["model_id"]
                    for role in ROLES if manager.options[role][manager.selections[role]].get("transport") == COMPAT}

    def servers_in_use(manager):
        out = {}
        if manager is not None:
            with manager.lock:
                for role in ROLES:
                    option = manager.options[role][manager.selections[role]]
                    if option.get("transport") == COMPAT:
                        out.setdefault(option["config"]["base_url"], []).append(role)
        return out

    def status(probe=True):
        manager = g.get("F_ROLES")
        compat = manager.compat if manager is not None else load_compat_config(root)
        out = {"ok": True, "base_url": compat["base_url"], "models": compat["models"],
               "detected_at": compat.get("detected_at"), "key_saved": bool(saved_key(compat)), "reachable": None,
               "error": None, "in_use": in_use(manager)}
        if probe:
            used, answers = servers_in_use(manager), {}
            for base in dict.fromkeys([compat["base_url"], *used]):
                try:
                    discover(g["http_requests"], base, saved_key(compat, base), timeout=(2, 4))
                    answers[base] = (True, None)
                except OpenRouterError as error:
                    answers[base] = (False, str(error)[:160])     # it answered oddly, or is not asked: say which
                except Exception:
                    answers[base] = (False, None)                 # nothing answers there
            out["reachable"], out["error"] = answers[compat["base_url"]]
            out["servers"] = [{"base_url": base, "roles": roles, "reachable": answers[base][0], "error": answers[base][1]}
                              for base, roles in used.items()]
        return out

    @app.route("/api/build_f/compat", methods=["GET"])
    def compat_get():
        return jsonify(status())

    @app.route("/api/build_f/compat/detect", methods=["POST"])
    def compat_detect():
        try:
            value = action_request("compat-detect")
            base = compat_base_url(value.get("base_url"))
            local_address(base)                 # public over plain http: refused before anything is asked or saved
            new_key = str(value.get("api_key") or "").strip()
            if new_key and not _KEY_RE.fullmatch(new_key):
                raise ValueError(KEY_REFUSED)       # before it is sent anywhere or saved
            # a saved key goes only to the address it was entered for
            key = new_key or saved_key(load_compat_config(root), base)
            try:
                models = discover(g["http_requests"], base, key)
            except OpenRouterError as error:
                return jsonify({"ok": False, "error": f"No usable answer from {base}: {str(error)[:160]}"}), 503
            except Exception:
                return jsonify({"ok": False, "error": f"Nothing answers at {base} — is the model server running?"}), 503
            manager = g.get("F_ROLES")
            with _SAVING:                       # one detect at a time reads the file, changes it and writes it back
                current = load_compat_config(root)
                bound = current.get("key_base_url")
                try:
                    if new_key:                 # only a key the server has just accepted is kept, bound to this address
                        if bound and bound != base:
                            # The old key's address comes off the disk before the key is replaced, and this
                            # address goes on after: the new key is never bound to the old key's address, and a
                            # write that fails in between leaves the key bound to no address.
                            save_compat_config(root, dict(current, key_base_url=None))
                        save_key(root / "brain" / ".env", new_key)
                        bound = base
                    save_compat_config(root, {"base_url": base, "key_base_url": bound,
                                              "models": merged_models(current["models"], models),
                                              "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                finally:
                    if manager is not None:
                        manager.reload_compat()     # what is in force is what is on disk, after a failed write too
            out = status(probe=False)
            out["reachable"] = True
            return jsonify(out)
        except PermissionError as error:
            return jsonify({"ok": False, "error": str(error)}), 403
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400

    @app.route("/api/build_f/compat/use", methods=["POST"])
    def compat_use():
        manager = g.get("F_ROLES")
        if manager is None:
            return jsonify({"ok": False, "error": "Model choices are not installed yet."}), 503
        try:
            value = action_request("compat-use")
            model = value.get("model")
            roles = value.get("roles") if isinstance(value.get("roles"), dict) else {}
            # force: after Unlock (f_controls), as for Ollama: work in flight keeps its model, new calls take this one
            force = value.get("force", False)
            if not isinstance(force, bool):
                raise ValueError("force must be true or false.")
            selections = {}
            for role in ROLES:
                name = roles.get(role, model)
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("Pick a detected model (one for all four roles, or one per role).")
                key = f"{role}:compat:{name.strip()}"
                if key not in manager.options[role]:
                    raise ValueError(f"{name} is not a detected model for the {role} role — detect models first.")
                selections[role] = key
            result = manager.set(selections, force=True) if force else manager.set(selections)
            return jsonify({"ok": True, "selections": result["selections"], "transport": result["transport"],
                            "in_use": in_use(manager)})
        except PermissionError as error:
            return jsonify({"ok": False, "error": str(error)}), 403
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        except RuntimeError as error:
            reasons = list(getattr(error, "reasons", None) or [])
            message = ("Model selection is busy: " + "; ".join(reasons) + ". Wait a moment, or press Unlock (she stops "
                       "what she is doing).") if reasons else "Model selection is busy. Wait for all speech and memory work to finish."
            return jsonify({"ok": False, "error": message, "code": "model_busy", "busy": reasons}), 409

    print("[compat] OpenAI-compatible model endpoints installed")
