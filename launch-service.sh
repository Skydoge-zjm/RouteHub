#!/usr/bin/env bash

set -euo pipefail

CONFIG="${ROUTER_PROXY_CONFIG:-$HOME/.router-proxy/router_config.json}"
CAPTURE_DIR="${ROUTER_PROXY_CAPTURE_DIR:-$HOME/.router-proxy/captures}"
STATS_LOG_PATH="${ROUTER_PROXY_STATS_DIR:-$HOME/.router-proxy/logs}"
UI_HOST="127.0.0.1"
UI_PORT="8340"
CAPTURE=0
CAPTURE_REQUEST=0
CAPTURE_RESPONSE=0
CAPTURE_HEADERS_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG="$2"
      shift 2
      ;;
    --capture-dir)
      CAPTURE_DIR="$2"
      shift 2
      ;;
    --stats-log-path)
      STATS_LOG_PATH="$2"
      shift 2
      ;;
    --ui-host)
      UI_HOST="$2"
      shift 2
      ;;
    --ui-port)
      UI_PORT="$2"
      shift 2
      ;;
    --capture)
      CAPTURE=1
      shift
      ;;
    --capture-request)
      CAPTURE_REQUEST=1
      shift
      ;;
    --capture-response)
      CAPTURE_RESPONSE=1
      shift
      ;;
    --capture-headers-only)
      CAPTURE_HEADERS_ONLY=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ARGS=(
  -m router_proxy.service
  --config "$CONFIG"
  --capture-dir "$CAPTURE_DIR"
  --stats-log-path "$STATS_LOG_PATH"
  --ui-host "$UI_HOST"
  --ui-port "$UI_PORT"
)

if [[ $CAPTURE -eq 1 ]]; then
  ARGS+=(--capture)
fi
if [[ $CAPTURE_REQUEST -eq 1 ]]; then
  ARGS+=(--capture-request)
fi
if [[ $CAPTURE_RESPONSE -eq 1 ]]; then
  ARGS+=(--capture-response)
fi
if [[ $CAPTURE_HEADERS_ONLY -eq 1 ]]; then
  ARGS+=(--capture-headers-only)
fi

python "${ARGS[@]}"
