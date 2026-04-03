from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .models import ProxyConfig, UpstreamConfig


@dataclass(slots=True)
class UpstreamState:
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    healthy: bool = True
    last_health_status: int | None = None
    last_error: str | None = None
    last_checked_at: float | None = None
    runtime_score: int = 0
    last_latency_ms: int | None = None
    success_count: int = 0
    failure_count: int = 0
    health_source: str | None = None
    last_failure_source: str | None = None
    circuit_trip_count: int = 0

    def status(self, enabled: bool) -> str:
        if not enabled:
            return "disabled"
        if self.circuit_open_until > time.time():
            return "circuit_open"
        if not self.healthy:
            return "unhealthy"
        return "healthy"


@dataclass(slots=True)
class FallbackProbeResult:
    ok: bool
    status: int | None = None
    error: str | None = None
    latency_ms: int | None = None


class UpstreamHealthManager:
    def __init__(
        self,
        config: ProxyConfig,
        fallback_probe: Callable[[UpstreamConfig], FallbackProbeResult] | None = None,
    ) -> None:
        self.config = config
        self.fallback_probe = fallback_probe
        self._lock = threading.Lock()
        self._states = {upstream.name: UpstreamState() for upstream in config.upstreams}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.health.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="upstream-health", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def get_state(self, upstream_name: str) -> UpstreamState:
        with self._lock:
            return self._states[upstream_name]

    def is_available(self, upstream_name: str) -> bool:
        with self._lock:
            state = self._states[upstream_name]
            return time.time() >= state.circuit_open_until

    def is_routable(self, upstream_name: str) -> bool:
        with self._lock:
            state = self._states[upstream_name]
            return state.healthy and time.time() >= state.circuit_open_until

    def record_success(self, upstream_name: str) -> None:
        self.record_success_with_latency(upstream_name, None, source="runtime_success")

    def record_success_with_latency(
        self,
        upstream_name: str,
        latency_ms: int | None,
        *,
        source: str = "runtime_success",
    ) -> None:
        with self._lock:
            state = self._states[upstream_name]
            state.consecutive_failures = 0
            state.circuit_open_until = 0.0
            state.healthy = True
            state.last_error = None
            state.success_count += 1
            state.last_latency_ms = latency_ms
            state.health_source = source
            state.last_failure_source = None
            state.circuit_trip_count = 0
            state.runtime_score = max(-100, min(100, state.runtime_score + self._latency_bonus(latency_ms)))

    def record_failure(self, upstream_name: str, error: str, *, source: str = "proxy_request") -> None:
        with self._lock:
            state = self._states[upstream_name]
            state.consecutive_failures += 1
            state.last_error = error
            state.failure_count += 1
            state.last_failure_source = source
            state.runtime_score = max(-100, min(100, state.runtime_score - 25))
            if (
                state.consecutive_failures >= self.config.routing.circuit_breaker_threshold
                and time.time() >= state.circuit_open_until
            ):
                state.circuit_trip_count += 1
                multiplier = min(
                    self.config.routing.circuit_breaker_max_cooldown_multiplier,
                    2 ** max(0, state.circuit_trip_count - 1),
                )
                state.circuit_open_until = time.time() + self.config.routing.circuit_breaker_cooldown_seconds * multiplier
                state.healthy = False

    def mark_unhealthy(
        self,
        upstream_name: str,
        *,
        status: int | None,
        error: str | None,
        source: str,
    ) -> None:
        with self._lock:
            state = self._states[upstream_name]
            state.last_checked_at = time.time()
            state.last_health_status = status
            state.last_error = error
            state.healthy = False
            state.last_failure_source = source

    def mark_healthy(
        self,
        upstream_name: str,
        *,
        status: int | None,
        source: str,
        latency_ms: int | None = None,
    ) -> None:
        with self._lock:
            state = self._states[upstream_name]
            state.last_checked_at = time.time()
            state.last_health_status = status
            state.last_error = None
            state.healthy = True
            state.health_source = source
            state.last_latency_ms = latency_ms

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.run_health_checks_once()
            self._stop_event.wait(self.config.health.interval_seconds)

    def run_health_checks_once(self) -> None:
        for upstream in self.config.upstreams:
            self._check_upstream(upstream)

    def run_health_check_for(self, upstream_name: str) -> None:
        for upstream in self.config.upstreams:
            if upstream.name == upstream_name:
                self._check_upstream(upstream)
                return
        raise ValueError(f"Unknown upstream: {upstream_name}")

    def reset_upstream(self, upstream_name: str) -> None:
        with self._lock:
            if upstream_name not in self._states:
                raise ValueError(f"Unknown upstream: {upstream_name}")
            state = self._states[upstream_name]
            state.consecutive_failures = 0
            state.circuit_open_until = 0.0
            state.healthy = True
            state.last_error = None
            state.runtime_score = 0
            state.last_latency_ms = None
            state.success_count = 0
            state.failure_count = 0
            state.health_source = "manual_reset"
            state.last_failure_source = None
            state.circuit_trip_count = 0

    def get_runtime_score(self, upstream_name: str) -> int:
        with self._lock:
            return self._states[upstream_name].runtime_score

    @staticmethod
    def _latency_bonus(latency_ms: int | None) -> int:
        if latency_ms is None:
            return 4
        if latency_ms <= 1000:
            return 15
        if latency_ms <= 3000:
            return 8
        if latency_ms <= 8000:
            return 3
        return 1

    def _check_upstream(self, upstream: UpstreamConfig) -> None:
        url = f"{upstream.base_url.rstrip('/')}{upstream.healthcheck_path}"
        request = urllib.request.Request(url, method="GET")
        if upstream.api_key:
            request.add_header("Authorization", f"Bearer {upstream.api_key}")
        try:
            with urllib.request.urlopen(request, timeout=self.config.health.timeout_seconds) as response:
                self.mark_healthy(upstream.name, status=response.status, source="healthcheck")
        except urllib.error.HTTPError as exc:
            self._handle_health_failure(upstream, status=exc.code, error=f"HTTP {exc.code}")
        except Exception as exc:
            self._handle_health_failure(upstream, status=None, error=str(exc))

    def _handle_health_failure(self, upstream: UpstreamConfig, *, status: int | None, error: str | None) -> None:
        if self.config.health.fallback_to_test_request and self.fallback_probe:
            result = self.fallback_probe(upstream)
            if result.ok:
                self.mark_healthy(
                    upstream.name,
                    status=result.status if result.status is not None else status,
                    source="fallback_test",
                    latency_ms=result.latency_ms,
                )
                return
            fallback_error = result.error or error
            self.mark_unhealthy(
                upstream.name,
                status=result.status if result.status is not None else status,
                error=fallback_error,
                source="fallback_test",
            )
            return

        self.mark_unhealthy(upstream.name, status=status, error=error, source="healthcheck")
