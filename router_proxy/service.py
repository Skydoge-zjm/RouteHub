from __future__ import annotations

import argparse
import time
from pathlib import Path

from config_ui.server import create_ui_server

from .capture import CaptureMode
from .config import DEFAULT_CONFIG_PATH, user_data_dir
from .server import RouterProxyRuntime, build_capture_mode


def parse_args() -> argparse.Namespace:
    data_dir = user_data_dir()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--capture-dir", default=str(data_dir / "captures"))
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--capture-request", action="store_true")
    parser.add_argument("--capture-response", action="store_true")
    parser.add_argument("--capture-headers-only", action="store_true")
    parser.add_argument("--stats-log-path", default=str(data_dir / "logs"))
    parser.add_argument("--ui-host", default="127.0.0.1")
    parser.add_argument("--ui-port", type=int, default=8340)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capture_mode: CaptureMode = build_capture_mode(args)
    runtime = RouterProxyRuntime(
        config_path=Path(args.config),
        capture_mode=capture_mode,
        capture_dir=Path(args.capture_dir),
        stats_log_path=Path(args.stats_log_path),
    )
    runtime.start()
    ui_server = create_ui_server(
        host=args.ui_host,
        port=args.ui_port,
        config_path=Path(args.config),
        status_provider=runtime.snapshot_status,
        stats_provider=runtime.snapshot_stats,
        reload_callback=runtime.reload,
        healthcheck_callback=runtime.run_health_checks,
        test_request_callback=runtime.run_test_request,
        reset_upstream_callback=runtime.reset_upstream,
    )
    print(f"Admin UI listening on http://{args.ui_host}:{args.ui_port}")
    try:
        ui_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ui_server.server_close()
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
