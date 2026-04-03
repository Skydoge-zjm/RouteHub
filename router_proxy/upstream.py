from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

from .models import ProxyConfig, UpstreamConfig
from .health import UpstreamHealthManager


class UpstreamSelectionError(Exception):
    pass


@dataclass(slots=True)
class PreparedRequest:
    model: str | None
    body_text: str
    body_json: object
    headers: dict[str, str]
    raw_body: bytes


@dataclass(slots=True)
class UpstreamResult:
    upstream: UpstreamConfig
    status: int
    headers: dict[str, str]
    body: bytes
    streaming: bool


def parse_request(headers: dict[str, str], body: bytes) -> PreparedRequest:
    body_text = body.decode("utf-8", errors="replace")
    body_json = None
    model = None
    content_type = headers.get("content-type", headers.get("Content-Type", ""))
    if "application/json" in content_type.lower() and body:
        try:
            body_json = json.loads(body_text)
            if isinstance(body_json, dict):
                value = body_json.get("model")
                if isinstance(value, str):
                    model = value
        except json.JSONDecodeError:
            body_json = None
    return PreparedRequest(
        model=model,
        body_text=body_text,
        body_json=body_json,
        headers=headers,
        raw_body=body,
    )


def choose_upstreams(config: ProxyConfig, prepared: PreparedRequest) -> list[UpstreamConfig]:
    return [
        upstream
        for upstream in sorted(config.upstreams, key=lambda item: item.priority, reverse=True)
        if upstream.enabled
        and (not prepared.model or not upstream.supported_models or prepared.model in upstream.supported_models)
    ]


def filter_available_upstreams(
    config: ProxyConfig,
    prepared: PreparedRequest,
    health_manager: UpstreamHealthManager | None,
) -> list[UpstreamConfig]:
    candidates = []
    for upstream in choose_upstreams(config, prepared):
        if health_manager and not health_manager.is_routable(upstream.name):
            continue
        candidates.append(upstream)
    if not candidates:
        raise UpstreamSelectionError("No enabled upstream matched the request.")
    return sort_upstreams(config, candidates, health_manager)


def sort_upstreams(
    config: ProxyConfig,
    upstreams: list[UpstreamConfig],
    health_manager: UpstreamHealthManager | None,
) -> list[UpstreamConfig]:
    mode = config.routing.mode
    if mode == "strict_priority":
        return sorted(upstreams, key=lambda item: (-item.priority, item.name))
    if mode == "smart":
        def smart_key(item: UpstreamConfig):
            runtime_score = health_manager.get_runtime_score(item.name) if health_manager else 0
            final_score = item.priority * 1000 + runtime_score
            return (-final_score, -item.priority, item.name)
        return sorted(upstreams, key=smart_key)
    return sorted(upstreams, key=lambda item: (-item.priority, item.name))


def should_failover(status_code: int, config: ProxyConfig) -> bool:
    return status_code in config.routing.failover_statuses


def build_upstream_request(
    upstream: UpstreamConfig,
    path: str,
    method: str,
    headers: dict[str, str],
    body: bytes,
    body_json: object,
) -> urllib.request.Request:
    url = f"{upstream.base_url.rstrip('/')}{path}"
    request_body = body
    if isinstance(body_json, dict) and upstream.model_map:
        mapped_body = dict(body_json)
        model = mapped_body.get("model")
        if isinstance(model, str) and model in upstream.model_map:
            mapped_body["model"] = upstream.model_map[model]
            request_body = json.dumps(mapped_body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=request_body if method in {"POST", "PUT", "PATCH"} else None,
        method=method,
    )
    for key, value in headers.items():
        key_lower = key.lower()
        if key_lower in {"host", "content-length", "connection"}:
            continue
        if key_lower == "authorization" and upstream.api_key:
            continue
        request.add_header(key, value)
    if upstream.api_key:
        request.add_header("Authorization", f"Bearer {upstream.api_key}")
    return request


def open_upstream(
    config: ProxyConfig,
    upstream: UpstreamConfig,
    path: str,
    method: str,
    headers: dict[str, str],
    body: bytes,
    body_json: object,
):
    request = build_upstream_request(upstream, path, method, headers, body, body_json)
    timeout = config.routing.read_timeout_seconds
    return urllib.request.urlopen(request, timeout=timeout)


def send_test_request(
    config: ProxyConfig,
    upstream: UpstreamConfig,
    model: str,
    prompt: str,
):
    body_json = {
        "model": model,
        "input": prompt,
        "stream": False,
        "text": {"verbosity": "low"},
    }
    body = json.dumps(body_json, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    return open_upstream(
        config=config,
        upstream=upstream,
        path="/v1/responses",
        method="POST",
        headers=headers,
        body=body,
        body_json=body_json,
    )


def pick_probe_model(config: ProxyConfig, upstream: UpstreamConfig) -> str:
    if upstream.supported_models:
        return upstream.supported_models[0]
    if upstream.model_map:
        return next(iter(upstream.model_map.keys()))
    return config.health.fallback_test_model


def is_retryable_exception(exc: Exception) -> bool:
    return isinstance(exc, (urllib.error.URLError, TimeoutError, socket.timeout))
