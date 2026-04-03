from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


def utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


class CaptureMode:
    def __init__(
        self,
        enabled: bool,
        capture_request: bool,
        capture_response: bool,
        headers_only: bool,
    ) -> None:
        self.enabled = enabled
        self.capture_request = capture_request
        self.capture_response = capture_response
        self.headers_only = headers_only


class CaptureWriter:
    def __init__(self, mode: CaptureMode, capture_dir: Path) -> None:
        self.mode = mode
        self.capture_dir = capture_dir
        if self.mode.enabled:
            self.capture_dir.mkdir(parents=True, exist_ok=True)

    def _target_dir(self, request_id: str) -> Path:
        if len(request_id) < 8:
            return self.capture_dir
        date_text = request_id[:8]
        return self.capture_dir / date_text[:4] / date_text[4:6] / date_text[6:8]

    def write_request(
        self,
        request_id: str,
        method: str,
        path: str,
        upstream_url: str,
        client_address: str,
        headers: dict[str, str],
        body_text: str,
        body_json: object,
        upstream_name: str,
    ) -> None:
        if not self.mode.enabled or not self.mode.capture_request:
            return
        payload = {
            "id": request_id,
            "timestamp_utc": request_id,
            "method": method,
            "path": path,
            "upstream_url": upstream_url,
            "upstream_name": upstream_name,
            "client_address": client_address,
            "headers": headers,
        }
        if not self.mode.headers_only:
            payload["body_text"] = body_text
            payload["body_json"] = body_json
        target_dir = self._target_dir(request_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / f"{request_id}.request.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def write_response(
        self,
        request_id: str,
        status: int,
        headers: dict[str, str],
        body_text: str,
        upstream_name: str,
    ) -> None:
        if not self.mode.enabled or not self.mode.capture_response:
            return
        payload = {
            "id": request_id,
            "status": status,
            "upstream_name": upstream_name,
            "headers": headers,
        }
        if not self.mode.headers_only:
            payload["body_text"] = body_text
        target_dir = self._target_dir(request_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / f"{request_id}.response.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
