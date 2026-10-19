"""Keeps other websites from driving the local API through the user's browser.

The server trusts requests from this computer (no API key needed on loopback), so a page on any
website could otherwise make the browser send requests to http://127.0.0.1:11435:

* cross-site requests: a "simple" POST (text/plain body, no preflight) still reaches the handler
  even though the page cannot read the answer. Browsers send an Origin header with every
  cross-origin POST/PUT/PATCH/DELETE and Sec-Fetch-Site with every request, so those are checked.
* DNS rebinding: a hostile domain re-resolved to 127.0.0.1 makes the page same-origin with the API,
  so it can also read answers. The Host header then carries that domain, so it is checked too.

Requests without an Origin header (curl, Ollama/OpenAI SDKs, the airllm CLI) are unaffected.

Environment variables (both optional, comma-separated):
  AIRLLM_ORIGINS        extra browser origins allowed to call the API, e.g. http://localhost:3000;
                        "*" allows any origin (not recommended)
  AIRLLM_ALLOWED_HOSTS  extra host names the server may be reached by, e.g. gpu-box.lan
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from urllib.parse import urlparse

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::"})


def env_list(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def host_name(host_header: str) -> str:
    """'Example.LAN:11435' -> 'example.lan', '[::1]:11435' -> '::1'."""
    value = host_header.strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value[1:]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def allowed_host_names(bind_host: str | None = None) -> frozenset[str]:
    """Names the server may be addressed by: loopback, the name it was told to bind, AIRLLM_ALLOWED_HOSTS."""
    names = set(LOOPBACK_NAMES)
    if bind_host and bind_host.strip().lower() not in WILDCARD_BINDS:
        names.add(host_name(bind_host))
    names.update(host_name(h) for h in env_list("AIRLLM_ALLOWED_HOSTS"))
    return frozenset(names)


def host_allowed(host_header: str | None, allowed: frozenset[str]) -> bool:
    """IP literals are always fine (DNS rebinding needs a domain name); names must be allowlisted."""
    if not host_header:
        return True                       # HTTP/1.0 clients; browsers always send Host
    name = host_name(host_header)
    if name in allowed:
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


def origin_allowed(origin: str | None, host_header: str | None, extra: frozenset[str]) -> bool:
    """No Origin (non-browser client), the server's own origin, or an AIRLLM_ORIGINS entry."""
    if origin is None:
        return True
    value = normalize_origin(origin)
    if "*" in extra or value in extra:
        return True
    parsed = urlparse(value)
    return (parsed.scheme in ("http", "https") and bool(host_header)
            and parsed.netloc == host_header.strip().lower())


def request_allowed(headers, allowed_hosts: frozenset[str], extra_origins: frozenset[str],
                    api_path: bool) -> tuple[bool, int, str]:
    """(ok, status, message) for one request. `headers` is any case-insensitive mapping."""
    host = headers.get("host")
    if not host_allowed(host, allowed_hosts):
        return False, 400, ("Host header not allowed. To reach the server by this name, add it to "
                            "AIRLLM_ALLOWED_HOSTS.")
    if not api_path:
        return True, 200, ""
    origin = headers.get("origin")
    if origin is not None and not origin_allowed(origin, host, extra_origins):
        return False, 403, (f"Origin {origin} is not allowed to use this API. To allow a web app, "
                            "add its origin to AIRLLM_ORIGINS.")
    if origin is None and headers.get("sec-fetch-site") == "cross-site":
        return False, 403, "Cross-site requests are not allowed. Add the site to AIRLLM_ORIGINS."
    return True, 200, ""


def api_key_matches(header: str, api_key: str) -> bool:
    return hmac.compare_digest(header.encode(), f"Bearer {api_key}".encode())
