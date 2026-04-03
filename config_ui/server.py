from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Callable

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    ROOT = Path(sys._MEIPASS) / "config_ui"
else:
    ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT.parent))

from router_proxy.config import DEFAULT_CONFIG_PATH, ensure_config_file, load_config


def read_json(path: Path) -> dict:
    ensure_config_file(path)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ConfigUIHandler(BaseHTTPRequestHandler):
    config_path: Path
    status_provider: Callable[[], dict] | None = None
    stats_provider: Callable[[int | None, bool, int, int], dict] | None = None
    reload_callback: Callable[[], None] | None = None
    healthcheck_callback: Callable[[str | None], dict] | None = None
    test_request_callback: Callable[[str, str, str], dict] | None = None
    reset_upstream_callback: Callable[[str], dict] | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self._send_json(HTTPStatus.OK, read_json(self.config_path))
            return
        if parsed.path == "/api/status":
            payload = self.status_provider() if self.status_provider else {"running": False}
            self._send_json(HTTPStatus.OK, payload)
            return
        if parsed.path == "/api/stats":
            since_seconds = None
            hide_fallback_logs = False
            page = 1
            page_size = 100
            raw_since = parse_qs(parsed.query).get("since_seconds", [None])[0]
            raw_hide_fallback = parse_qs(parsed.query).get("hide_fallback_logs", [None])[0]
            raw_page = parse_qs(parsed.query).get("page", [None])[0]
            raw_page_size = parse_qs(parsed.query).get("page_size", [None])[0]
            if raw_since not in (None, ""):
                try:
                    since_seconds = int(raw_since)
                except ValueError:
                    since_seconds = None
            if raw_hide_fallback not in (None, ""):
                hide_fallback_logs = str(raw_hide_fallback).strip().lower() in {"1", "true", "yes", "on"}
            if raw_page not in (None, ""):
                try:
                    page = int(raw_page)
                except ValueError:
                    page = 1
            if raw_page_size not in (None, ""):
                try:
                    page_size = int(raw_page_size)
                except ValueError:
                    page_size = 100
            payload = (
                self.stats_provider(since_seconds, hide_fallback_logs, page, page_size)
                if self.stats_provider
                else {"summary_by_upstream": {}, "recent": []}
            )
            self._send_json(HTTPStatus.OK, payload)
            return
        if parsed.path == "/api/validate":
            try:
                config = load_config(self.config_path)
                payload = {
                    "ok": True,
                    "summary": {
                        "listen": {"host": config.listen.host, "port": config.listen.port},
                        "upstream_count": len(config.upstreams),
                        "enabled_upstreams": len([u for u in config.upstreams if u.enabled]),
                    },
                }
            except Exception as exc:
                payload = {"ok": False, "error": str(exc)}
            self._send_json(HTTPStatus.OK, payload)
            return

        self._serve_static(parsed.path)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/config":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Config payload must be a JSON object.")

            temp_path = self.config_path.with_suffix(".json.tmp")
            write_json(temp_path, payload)
            load_config(temp_path)
            temp_path.replace(self.config_path)
            if self.reload_callback:
                self.reload_callback()
            self._send_json(HTTPStatus.OK, {"ok": True})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/reload":
            try:
                if self.reload_callback:
                    self.reload_callback()
                self._send_json(HTTPStatus.OK, {"ok": True})
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/healthcheck":
            try:
                payload = self._read_json_body()
                upstream_name = payload.get("upstream_name") if isinstance(payload, dict) else None
                if self.healthcheck_callback:
                    result = {
                        "ok": True,
                        "status": self.healthcheck_callback(upstream_name),
                    }
                else:
                    result = {"ok": False, "error": "Health check callback not configured."}
                self._send_json(HTTPStatus.OK, result)
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/test-request":
            try:
                payload = self._read_json_body()
                if not isinstance(payload, dict):
                    raise ValueError("Payload must be a JSON object.")
                upstream_name = str(payload.get("upstream_name") or "").strip()
                model = str(payload.get("model") or "").strip()
                prompt = str(payload.get("prompt") or "").strip()
                if not upstream_name:
                    raise ValueError("upstream_name is required.")
                if not model:
                    raise ValueError("model is required.")
                if not prompt:
                    raise ValueError("prompt is required.")
                if self.test_request_callback:
                    result = self.test_request_callback(upstream_name, model, prompt)
                else:
                    result = {"ok": False, "error": "Test request callback not configured."}
                self._send_json(HTTPStatus.OK, result)
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/upstream/reset":
            try:
                payload = self._read_json_body()
                upstream_name = str(payload.get("upstream_name") or "").strip()
                if not upstream_name:
                    raise ValueError("upstream_name is required.")
                if self.reset_upstream_callback:
                    result = {"ok": True, "status": self.reset_upstream_callback(upstream_name)}
                else:
                    result = {"ok": False, "error": "Reset callback not configured."}
                self._send_json(HTTPStatus.OK, result)
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def log_message(self, format: str, *args) -> None:
        return

    def _serve_static(self, raw_path: str) -> None:
        path = raw_path.strip("/") or "index.html"
        target = (STATIC_DIR / path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists() or not target.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        content = target.read_bytes()
        content_type, _ = mimetypes.guess_type(target.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_handler(
    config_path: Path,
    status_provider: Callable[[], dict] | None = None,
    stats_provider: Callable[[int | None, bool, int, int], dict] | None = None,
    reload_callback: Callable[[], None] | None = None,
    healthcheck_callback: Callable[[str | None], dict] | None = None,
    test_request_callback: Callable[[str, str, str], dict] | None = None,
    reset_upstream_callback: Callable[[str], dict] | None = None,
):
    class BoundHandler(ConfigUIHandler):
        pass

    BoundHandler.config_path = config_path
    BoundHandler.status_provider = status_provider
    BoundHandler.stats_provider = stats_provider
    BoundHandler.reload_callback = reload_callback
    BoundHandler.healthcheck_callback = healthcheck_callback
    BoundHandler.test_request_callback = test_request_callback
    BoundHandler.reset_upstream_callback = reset_upstream_callback
    return BoundHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8340)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    server = create_ui_server(args.host, args.port, config_path)
    print(f"Config UI listening on http://{args.host}:{args.port}")
    print(f"Editing config: {config_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def create_ui_server(
    host: str,
    port: int,
    config_path: Path,
    status_provider: Callable[[], dict] | None = None,
    stats_provider: Callable[[int | None, bool, int, int], dict] | None = None,
    reload_callback: Callable[[], None] | None = None,
    healthcheck_callback: Callable[[str | None], dict] | None = None,
    test_request_callback: Callable[[str, str, str], dict] | None = None,
    reset_upstream_callback: Callable[[str], dict] | None = None,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port),
        build_handler(
            config_path=config_path,
            status_provider=status_provider,
            stats_provider=stats_provider,
            reload_callback=reload_callback,
            healthcheck_callback=healthcheck_callback,
            test_request_callback=test_request_callback,
            reset_upstream_callback=reset_upstream_callback,
        ),
    )
