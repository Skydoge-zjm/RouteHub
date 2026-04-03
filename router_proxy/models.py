from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ListenConfig:
    host: str = "127.0.0.1"
    port: int = 8330


@dataclass(slots=True)
class RoutingConfig:
    mode: str = "strict_priority"
    connect_timeout_seconds: int = 10
    read_timeout_seconds: int = 120
    failover_statuses: list[int] = field(
        default_factory=lambda: [408, 409, 425, 429, 500, 502, 503, 504]
    )
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown_seconds: int = 60
    circuit_breaker_max_cooldown_multiplier: int = 8


@dataclass(slots=True)
class HealthConfig:
    enabled: bool = True
    interval_seconds: int = 120
    timeout_seconds: int = 5
    healthy_statuses: list[int] = field(default_factory=lambda: [200, 204, 401, 403, 405])
    fallback_to_test_request: bool = True
    fallback_test_model: str = "gpt-5.4"
    fallback_test_prompt: str = "Reply with OK."


@dataclass(slots=True)
class UpstreamConfig:
    name: str
    base_url: str
    api_key: str | None = None
    priority: int = 100
    enabled: bool = True
    supports_stream: bool = True
    supported_models: list[str] = field(default_factory=list)
    model_map: dict[str, str] = field(default_factory=dict)
    healthcheck_path: str = "/v1/models"


@dataclass(slots=True)
class ProxyConfig:
    listen: ListenConfig
    routing: RoutingConfig
    health: HealthConfig
    upstreams: list[UpstreamConfig]
