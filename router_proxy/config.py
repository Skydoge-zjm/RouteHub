from __future__ import annotations

import os
import json
from pathlib import Path

from .models import HealthConfig, ListenConfig, ProxyConfig, RoutingConfig, UpstreamConfig


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_CONFIG_PATH = PROJECT_ROOT / "router_config.json"
PROJECT_CONFIG_EXAMPLE_PATH = PROJECT_ROOT / "router_config.example.json"


def user_config_path() -> Path:
    override = os.environ.get("ROUTER_PROXY_CONFIG")
    if override:
        return Path(override).expanduser()
    return user_data_dir() / "router_config.json"


def user_data_dir() -> Path:
    return Path.home() / ".router-proxy"


def resolve_default_config_path() -> Path:
    return user_config_path()


DEFAULT_CONFIG_PATH = resolve_default_config_path()


def default_config_dict() -> dict:
    return {
        "listen": {
            "host": "127.0.0.1",
            "port": 8330,
        },
        "routing": {
            "mode": "smart",
            "connect_timeout_seconds": 10,
            "read_timeout_seconds": 120,
            "failover_statuses": [408, 409, 425, 429, 500, 502, 503, 504],
            "circuit_breaker_threshold": 3,
            "circuit_breaker_cooldown_seconds": 60,
            "circuit_breaker_max_cooldown_multiplier": 8,
        },
        "health": {
            "enabled": True,
            "interval_seconds": 30,
            "timeout_seconds": 5,
            "healthy_statuses": [200, 204, 401, 403, 405],
            "fallback_to_test_request": True,
            "fallback_test_model": "gpt-5.4",
            "fallback_test_prompt": "Reply with OK.",
        },
        "upstreams": [],
    }


def ensure_config_file(path: Path) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_config_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _parse_listen(data: dict) -> ListenConfig:
    return ListenConfig(
        host=data.get("host", "127.0.0.1"),
        port=int(data.get("port", 8330)),
    )


def _parse_routing(data: dict) -> RoutingConfig:
    mode = data.get("mode", data.get("strategy", "strict_priority"))
    if mode == "priority":
        mode = "strict_priority"
    return RoutingConfig(
        mode=mode,
        connect_timeout_seconds=int(data.get("connect_timeout_seconds", 10)),
        read_timeout_seconds=int(data.get("read_timeout_seconds", 120)),
        failover_statuses=[int(value) for value in data.get("failover_statuses", [408, 409, 425, 429, 500, 502, 503, 504])],
        circuit_breaker_threshold=int(data.get("circuit_breaker_threshold", 3)),
        circuit_breaker_cooldown_seconds=int(data.get("circuit_breaker_cooldown_seconds", 60)),
        circuit_breaker_max_cooldown_multiplier=max(1, int(data.get("circuit_breaker_max_cooldown_multiplier", 8))),
    )


def _parse_health(data: dict) -> HealthConfig:
    return HealthConfig(
        enabled=bool(data.get("enabled", True)),
        interval_seconds=int(data.get("interval_seconds", 30)),
        timeout_seconds=int(data.get("timeout_seconds", 5)),
        healthy_statuses=[int(value) for value in data.get("healthy_statuses", [200, 204, 401, 403, 405])],
        fallback_to_test_request=bool(data.get("fallback_to_test_request", True)),
        fallback_test_model=str(data.get("fallback_test_model", "gpt-5.4")),
        fallback_test_prompt=str(data.get("fallback_test_prompt", "Reply with OK.")),
    )


def _parse_upstream(data: dict) -> UpstreamConfig:
    return UpstreamConfig(
        name=data["name"],
        base_url=data["base_url"],
        api_key=data.get("api_key"),
        priority=int(data.get("priority", 100)),
        enabled=bool(data.get("enabled", True)),
        supports_stream=bool(data.get("supports_stream", True)),
        supported_models=list(data.get("supported_models", [])),
        model_map=dict(data.get("model_map", {})),
        healthcheck_path=data.get("healthcheck_path", "/v1/models"),
    )


def load_config(path: Path) -> ProxyConfig:
    ensure_config_file(path)
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    listen = _parse_listen(raw.get("listen", {}))
    routing = _parse_routing(raw.get("routing", {}))
    health = _parse_health(raw.get("health", {}))
    upstreams = [_parse_upstream(item) for item in raw.get("upstreams", [])]
    return ProxyConfig(listen=listen, routing=routing, health=health, upstreams=upstreams)
