from __future__ import annotations

import argparse
import http.server
import socketserver
import sys
import threading
import time
import urllib.error
from pathlib import Path

from .capture import CaptureMode, CaptureWriter, utc_timestamp
from .config import DEFAULT_CONFIG_PATH, load_config, user_data_dir
from .health import FallbackProbeResult, UpstreamHealthManager
from .models import ProxyConfig
from .stats import StatsLogger
from .upstream import (
    filter_available_upstreams,
    is_retryable_exception,
    open_upstream,
    parse_request,
    pick_probe_model,
    send_test_request,
    should_failover,
)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def read_stream_chunks(response, response_headers: dict[str, str]):
    content_type = str(response_headers.get("Content-Type") or response_headers.get("content-type") or "").lower()
    if "text/event-stream" in content_type:
        while True:
            line = response.readline()
            if not line:
                break
            yield line
        return

    while True:
        chunk = response.read(4096)
        if not chunk:
            break
        yield chunk


def is_event_stream_response(response_headers: dict[str, str]) -> bool:
    content_type = str(response_headers.get("Content-Type") or response_headers.get("content-type") or "").lower()
    return "text/event-stream" in content_type


def make_handler(
    config: ProxyConfig,
    capture_writer: CaptureWriter,
    health_manager: UpstreamHealthManager | None,
    stats_logger: StatsLogger | None,
):
    class RoutingProxyHandler(http.server.BaseHTTPRequestHandler):
        server_version = "RouterProxy/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *values) -> None:
            sys.stdout.write(
                "%s - - [%s] %s\n"
                % (
                    self.address_string(),
                    self.log_date_time_string(),
                    format % values,
                )
            )

        def do_POST(self) -> None:
            self._handle_request()

        def do_GET(self) -> None:
            self._handle_request()

        def do_OPTIONS(self) -> None:
            self._handle_request()

        def _handle_request(self) -> None:
            request_id = utc_timestamp()
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            headers_dict = {k: v for k, v in self.headers.items()}
            prepared = parse_request(headers_dict, body)

            try:
                upstreams = filter_available_upstreams(config, prepared, health_manager)
            except Exception as exc:
                self._send_plain_error(503, str(exc))
                return

            last_error_status = None
            last_error_body = b""
            last_error_headers: dict[str, str] = {}
            last_error_upstream = None

            for upstream in upstreams:
                attempt_started = time.time()
                upstream_url = f"{upstream.base_url.rstrip('/')}{self.path}"
                capture_writer.write_request(
                    request_id=request_id,
                    method=self.command,
                    path=self.path,
                    upstream_url=upstream_url,
                    upstream_name=upstream.name,
                    client_address=self.client_address[0],
                    headers=headers_dict,
                    body_text=prepared.body_text,
                    body_json=prepared.body_json,
                )

                try:
                    with open_upstream(
                        config=config,
                        upstream=upstream,
                        path=self.path,
                        method=self.command,
                        headers=headers_dict,
                        body=body,
                        body_json=prepared.body_json,
                    ) as response:
                        self.send_response(response.status)
                        response_headers = dict(response.headers.items())
                        event_stream = is_event_stream_response(response_headers)
                        for key, value in response.headers.items():
                            if key.lower() in {"transfer-encoding", "connection", "server", "date"}:
                                continue
                            if event_stream and key.lower() == "content-length":
                                continue
                            self.send_header(key, value)
                        if event_stream:
                            self.send_header("Transfer-Encoding", "chunked")
                            self.send_header("Cache-Control", response_headers.get("Cache-Control", "no-cache"))
                            self.send_header("X-Accel-Buffering", "no")
                        self.end_headers()

                        response_chunks: list[bytes] = []
                        for chunk in read_stream_chunks(response, response_headers):
                            response_chunks.append(chunk)
                            if event_stream:
                                self.wfile.write(f"{len(chunk):X}\r\n".encode("ascii"))
                                self.wfile.write(chunk)
                                self.wfile.write(b"\r\n")
                            else:
                                self.wfile.write(chunk)
                            self.wfile.flush()
                        if event_stream:
                            self.wfile.write(b"0\r\n\r\n")
                            self.wfile.flush()

                        response_body = b"".join(response_chunks)
                        capture_writer.write_response(
                            request_id=request_id,
                            status=response.status,
                            headers=response_headers,
                            body_text=response_body.decode("utf-8", errors="replace"),
                            upstream_name=upstream.name,
                        )
                        elapsed_ms = round((time.time() - attempt_started) * 1000)
                        if stats_logger:
                            stats_logger.append(
                                event_type="proxy_request",
                                upstream_name=upstream.name,
                                request_path=self.path,
                                model=prepared.model,
                                status=response.status,
                                success=True,
                                elapsed_ms=elapsed_ms,
                                body_text=response_body.decode("utf-8", errors="replace"),
                            )
                        if health_manager:
                            health_manager.record_success_with_latency(upstream.name, elapsed_ms)
                        return
                except urllib.error.HTTPError as exc:
                    error_body = exc.read()
                    response_headers = dict(exc.headers.items())
                    capture_writer.write_response(
                        request_id=request_id,
                        status=exc.code,
                        headers=response_headers,
                        body_text=error_body.decode("utf-8", errors="replace"),
                        upstream_name=upstream.name,
                    )
                    if stats_logger:
                        stats_logger.append(
                            event_type="proxy_request",
                            upstream_name=upstream.name,
                            request_path=self.path,
                            model=prepared.model,
                            status=exc.code,
                            success=False,
                            elapsed_ms=round((time.time() - attempt_started) * 1000),
                            body_text=error_body.decode("utf-8", errors="replace"),
                            error=f"HTTP {exc.code}",
                        )
                    if health_manager:
                        health_manager.record_failure(upstream.name, f"HTTP {exc.code}", source="proxy_request")
                    if should_failover(exc.code, config):
                        last_error_status = exc.code
                        last_error_body = error_body
                        last_error_headers = response_headers
                        last_error_upstream = upstream.name
                        continue

                    self._relay_error(exc.code, response_headers, error_body)
                    return
                except Exception as exc:
                    if stats_logger:
                        stats_logger.append(
                            event_type="proxy_request",
                            upstream_name=upstream.name,
                            request_path=self.path,
                            model=prepared.model,
                            status=502,
                            success=False,
                            elapsed_ms=round((time.time() - attempt_started) * 1000),
                            body_text="",
                            error=str(exc),
                        )
                    if health_manager:
                        health_manager.record_failure(upstream.name, str(exc), source="proxy_request")
                    if is_retryable_exception(exc):
                        last_error_status = 502
                        last_error_body = str(exc).encode("utf-8", errors="replace")
                        last_error_headers = {"Content-Type": "text/plain; charset=utf-8"}
                        last_error_upstream = upstream.name
                        continue
                    self._send_plain_error(502, str(exc))
                    return

            detail = f"All upstreams failed. last_upstream={last_error_upstream or 'unknown'}"
            if last_error_status is not None:
                body_bytes = last_error_body or detail.encode("utf-8", errors="replace")
                self._relay_error(last_error_status, last_error_headers, body_bytes)
                return
            self._send_plain_error(502, detail)

        def _relay_error(self, status: int, headers: dict[str, str], body: bytes) -> None:
            self.send_response(status)
            for key, value in headers.items():
                if key.lower() in {"transfer-encoding", "connection", "server", "date"}:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def _send_plain_error(self, status: int, message: str) -> None:
            payload = message.encode("utf-8", errors="replace")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

    return RoutingProxyHandler


def build_capture_mode(args: argparse.Namespace) -> CaptureMode:
    if args.capture_headers_only:
        return CaptureMode(
            enabled=True,
            capture_request=args.capture_request or not args.capture_response,
            capture_response=args.capture_response or not args.capture_request,
            headers_only=True,
        )
    if args.capture_request or args.capture_response:
        return CaptureMode(
            enabled=True,
            capture_request=args.capture_request,
            capture_response=args.capture_response,
            headers_only=False,
        )
    if args.capture:
        return CaptureMode(
            enabled=True,
            capture_request=True,
            capture_response=True,
            headers_only=False,
        )
    return CaptureMode(
        enabled=False,
        capture_request=False,
        capture_response=False,
        headers_only=False,
    )


def run_server(config_path: Path, capture_mode: CaptureMode, capture_dir: Path, stats_log_path: Path) -> int:
    runtime = RouterProxyRuntime(
        config_path=config_path,
        capture_mode=capture_mode,
        capture_dir=capture_dir,
        stats_log_path=stats_log_path,
    )
    runtime.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop()
    return 0


class RouterProxyRuntime:
    def __init__(self, config_path: Path, capture_mode: CaptureMode, capture_dir: Path, stats_log_path: Path) -> None:
        self.config_path = config_path
        self.capture_mode = capture_mode
        self.capture_dir = capture_dir
        self.stats_log_path = stats_log_path
        self._lock = threading.RLock()
        self.config: ProxyConfig | None = None
        self.capture_writer: CaptureWriter | None = None
        self.health_manager: UpstreamHealthManager | None = None
        self.stats_logger = StatsLogger(stats_log_path)
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            self._start_locked()

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def reload(self) -> None:
        with self._lock:
            self._stop_locked()
            self._start_locked()

    def snapshot_status(self) -> dict:
        with self._lock:
            config = self.config
            health_manager = self.health_manager
            if not config:
                return {"running": False}
            upstreams = []
            for upstream in sorted(config.upstreams, key=lambda item: item.priority, reverse=True):
                state = health_manager.get_state(upstream.name) if health_manager else None
                upstreams.append(
                    {
                        "name": upstream.name,
                        "base_url": upstream.base_url,
                        "priority": upstream.priority,
                        "routing_mode": config.routing.mode,
                        "enabled": upstream.enabled,
                        "supported_models": upstream.supported_models,
                        "model_map": upstream.model_map,
                        "healthcheck_path": upstream.healthcheck_path,
                        "state": state.status(upstream.enabled) if state else ("healthy" if upstream.enabled else "disabled"),
                        "healthy": state.healthy if state else None,
                        "health_source": state.health_source if state else None,
                        "last_failure_source": state.last_failure_source if state else None,
                        "last_health_status": state.last_health_status if state else None,
                        "last_error": state.last_error if state else None,
                        "last_checked_at": state.last_checked_at if state else None,
                        "consecutive_failures": state.consecutive_failures if state else None,
                        "circuit_trip_count": state.circuit_trip_count if state else None,
                        "success_count": state.success_count if state else None,
                        "failure_count": state.failure_count if state else None,
                        "last_latency_ms": state.last_latency_ms if state else None,
                        "runtime_score": state.runtime_score if state else 0,
                        "effective_sort_score": (upstream.priority * 1000 + (state.runtime_score if state else 0)) if config.routing.mode == "smart" else upstream.priority,
                        "circuit_open": bool(state and state.circuit_open_until > time.time()),
                        "circuit_open_until": state.circuit_open_until if state else None,
                        "cooldown_remaining_seconds": max(0, round(state.circuit_open_until - time.time())) if state and state.circuit_open_until > time.time() else 0,
                    }
                )
            return {
                "running": self.thread.is_alive() if self.thread else False,
                "listen": {"host": config.listen.host, "port": config.listen.port},
                "routing": {"mode": config.routing.mode},
                "stats_log_path": self.stats_logger.describe_path(),
                "capture": {
                    "enabled": self.capture_mode.enabled,
                    "request": self.capture_mode.capture_request,
                    "response": self.capture_mode.capture_response,
                    "headers_only": self.capture_mode.headers_only,
                },
                "upstreams": upstreams,
            }

    def snapshot_stats(
        self,
        since_seconds: int | None = None,
        hide_fallback_logs: bool = False,
        page: int = 1,
        page_size: int = 100,
    ) -> dict:
        with self._lock:
            since_timestamp = None
            if since_seconds and since_seconds > 0:
                since_timestamp = time.time() - since_seconds
            exclude_event_types = {"health_fallback_test"} if hide_fallback_logs else None
            safe_page_size = max(1, page_size)
            _, total = self.stats_logger.read_recent_page(
                page=1,
                page_size=safe_page_size,
                since_timestamp=since_timestamp,
                exclude_event_types=exclude_event_types,
            )
            total_pages = max(1, (total + safe_page_size - 1) // safe_page_size)
            safe_page = min(max(1, page), total_pages)
            recent, _ = self.stats_logger.read_recent_page(
                page=safe_page,
                page_size=safe_page_size,
                since_timestamp=since_timestamp,
                exclude_event_types=exclude_event_types,
            )
            return {
                "log_path": self.stats_logger.describe_path(),
                "summary_by_upstream": self.stats_logger.summary_by_upstream(since_timestamp=since_timestamp),
                "recent": recent,
                "recent_pagination": {
                    "page": safe_page,
                    "page_size": safe_page_size,
                    "total": total,
                    "total_pages": total_pages,
                },
            }

    def run_health_checks(self, upstream_name: str | None = None) -> dict:
        with self._lock:
            if not self.health_manager:
                raise RuntimeError("Health manager is not running.")
            if upstream_name:
                self.health_manager.run_health_check_for(upstream_name)
            else:
                self.health_manager.run_health_checks_once()
            return self.snapshot_status()

    def run_test_request(self, upstream_name: str, model: str, prompt: str) -> dict:
        with self._lock:
            if not self.config:
                raise RuntimeError("Proxy runtime is not started.")
            upstream = next((item for item in self.config.upstreams if item.name == upstream_name), None)
            if not upstream:
                raise ValueError(f"Unknown upstream: {upstream_name}")
            started = time.time()
            try:
                with send_test_request(self.config, upstream, model, prompt) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    if self.health_manager:
                        self.health_manager.record_success_with_latency(
                            upstream.name,
                            round((time.time() - started) * 1000),
                            source="manual_test",
                        )
                    self.stats_logger.append(
                        event_type="test_request",
                        upstream_name=upstream.name,
                        request_path="/v1/responses",
                        model=model,
                        status=response.status,
                        success=True,
                        elapsed_ms=round((time.time() - started) * 1000),
                        body_text=body,
                    )
                    return {
                        "ok": True,
                        "upstream": upstream.name,
                        "status": response.status,
                        "elapsed_ms": round((time.time() - started) * 1000),
                        "body_text": body,
                    }
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if self.health_manager:
                    self.health_manager.record_failure(upstream.name, f"HTTP {exc.code}", source="test_request")
                self.stats_logger.append(
                    event_type="test_request",
                    upstream_name=upstream.name,
                    request_path="/v1/responses",
                    model=model,
                    status=exc.code,
                    success=False,
                    elapsed_ms=round((time.time() - started) * 1000),
                    body_text=body,
                    error=f"HTTP {exc.code}",
                )
                return {
                    "ok": False,
                    "upstream": upstream.name,
                    "status": exc.code,
                    "elapsed_ms": round((time.time() - started) * 1000),
                    "body_text": body,
                }
            except Exception as exc:
                if self.health_manager:
                    self.health_manager.record_failure(upstream.name, str(exc), source="test_request")
                self.stats_logger.append(
                    event_type="test_request",
                    upstream_name=upstream.name,
                    request_path="/v1/responses",
                    model=model,
                    status=502,
                    success=False,
                    elapsed_ms=round((time.time() - started) * 1000),
                    body_text="",
                    error=str(exc),
                )
                return {
                    "ok": False,
                    "upstream": upstream.name,
                    "status": 502,
                    "elapsed_ms": round((time.time() - started) * 1000),
                    "body_text": str(exc),
                }

    def reset_upstream(self, upstream_name: str) -> dict:
        with self._lock:
            if not self.health_manager:
                raise RuntimeError("Health manager is not running.")
            self.health_manager.reset_upstream(upstream_name)
            return self.snapshot_status()

    def _start_locked(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.config = load_config(self.config_path)
        self.capture_writer = CaptureWriter(mode=self.capture_mode, capture_dir=self.capture_dir)
        self.health_manager = UpstreamHealthManager(self.config, fallback_probe=self._run_fallback_probe)
        self.health_manager.start()
        handler = make_handler(self.config, self.capture_writer, self.health_manager, self.stats_logger)
        self.server = ThreadingHTTPServer((self.config.listen.host, self.config.listen.port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="router-proxy", daemon=True)
        self.thread.start()

        print(f"Listening on http://{self.config.listen.host}:{self.config.listen.port}")
        print(f"Loaded config: {self.config_path}")
        print(f"Capture enabled: {self.capture_mode.enabled}")
        if self.capture_mode.enabled:
            print(f"Capturing into {self.capture_dir}")
            print(
                f"Capture options: request={self.capture_mode.capture_request} response={self.capture_mode.capture_response} headers_only={self.capture_mode.headers_only}"
            )
        print("Upstreams:")
        for upstream in sorted(self.config.upstreams, key=lambda item: item.priority, reverse=True):
            print(
                f"  - {upstream.name}: priority={upstream.priority} enabled={upstream.enabled} base_url={upstream.base_url}"
            )

    def _stop_locked(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.health_manager:
            self.health_manager.stop()
            self.health_manager = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        self.thread = None

    def _run_fallback_probe(self, upstream) -> FallbackProbeResult:
        if not self.config:
            return FallbackProbeResult(ok=False, error="Proxy runtime is not started.")
        model = pick_probe_model(self.config, upstream)
        prompt = self.config.health.fallback_test_prompt
        started = time.time()
        try:
            with send_test_request(self.config, upstream, model, prompt) as response:
                body = response.read().decode("utf-8", errors="replace")
                elapsed_ms = round((time.time() - started) * 1000)
                self.stats_logger.append(
                    event_type="health_fallback_test",
                    upstream_name=upstream.name,
                    request_path="/v1/responses",
                    model=model,
                    status=response.status,
                    success=True,
                    elapsed_ms=elapsed_ms,
                    body_text=body,
                )
                return FallbackProbeResult(ok=True, status=response.status, latency_ms=elapsed_ms)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            self.stats_logger.append(
                event_type="health_fallback_test",
                upstream_name=upstream.name,
                request_path="/v1/responses",
                model=model,
                status=exc.code,
                success=False,
                elapsed_ms=round((time.time() - started) * 1000),
                body_text=body,
                error=f"HTTP {exc.code}",
            )
            return FallbackProbeResult(ok=False, status=exc.code, error=f"HTTP {exc.code}")
        except Exception as exc:
            self.stats_logger.append(
                event_type="health_fallback_test",
                upstream_name=upstream.name,
                request_path="/v1/responses",
                model=model,
                status=502,
                success=False,
                elapsed_ms=round((time.time() - started) * 1000),
                body_text="",
                error=str(exc),
            )
            return FallbackProbeResult(ok=False, status=502, error=str(exc))


def parse_args() -> argparse.Namespace:
    data_dir = user_data_dir()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--capture-dir", default=str(data_dir / "captures"))
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--capture-request", action="store_true")
    parser.add_argument("--capture-response", action="store_true")
    parser.add_argument("--capture-headers-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_server(
        config_path=Path(args.config),
        capture_mode=build_capture_mode(args),
        capture_dir=Path(args.capture_dir),
        stats_log_path=user_data_dir() / "logs",
    )


if __name__ == "__main__":
    raise SystemExit(main())
