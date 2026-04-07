from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


def _extract_usage_from_response_json(payload: dict) -> UsageStats:
    response = payload.get("response", payload)
    usage = response.get("usage") or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    return UsageStats(
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        cached_tokens=int(input_details.get("cached_tokens") or 0),
        reasoning_tokens=int(output_details.get("reasoning_tokens") or 0),
    )


def extract_usage(body_text: str) -> UsageStats:
    body_text = body_text.strip()
    if not body_text:
        return UsageStats()

    try:
        payload = json.loads(body_text)
        if isinstance(payload, dict):
            return _extract_usage_from_response_json(payload)
    except json.JSONDecodeError:
        pass

    last_completed = None
    for line in body_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("type") == "response.completed":
            last_completed = payload

    if isinstance(last_completed, dict):
        return _extract_usage_from_response_json(last_completed)
    return UsageStats()


class StatsLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.single_file_mode = self.log_path.suffix.lower() == ".jsonl"
        if self.single_file_mode:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.log_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def current_log_path(self, timestamp: float | None = None) -> Path:
        if self.single_file_mode:
            return self.log_path
        now = datetime.fromtimestamp(timestamp or time.time(), tz=timezone.utc)
        return (
            self.log_path
            / f"{now.year:04d}"
            / f"{now.month:02d}"
            / f"{now.day:02d}"
            / "request_stats.jsonl"
        )

    def describe_path(self) -> str:
        if self.single_file_mode:
            return str(self.log_path)
        return str(self.log_path / "YYYY" / "MM" / "DD" / "request_stats.jsonl")

    def _iter_log_files(self) -> list[Path]:
        if self.single_file_mode:
            return [self.log_path] if self.log_path.exists() else []
        if not self.log_path.exists():
            return []
        return sorted(self.log_path.rglob("*.jsonl"))

    def append(
        self,
        *,
        event_type: str,
        upstream_name: str,
        request_path: str,
        model: str | None,
        status: int,
        success: bool,
        elapsed_ms: int,
        body_text: str = "",
        error: str | None = None,
    ) -> None:
        usage = extract_usage(body_text)
        timestamp = time.time()
        record = {
            "timestamp": timestamp,
            "event_type": event_type,
            "upstream_name": upstream_name,
            "request_path": request_path,
            "model": model,
            "status": status,
            "success": success,
            "elapsed_ms": elapsed_ms,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "cached_tokens": usage.cached_tokens,
                "reasoning_tokens": usage.reasoning_tokens,
            },
            "error": error,
        }
        line = json.dumps(record, ensure_ascii=False)
        target_path = self.current_log_path(timestamp)
        with self._lock:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def _iter_records(self) -> list[dict]:
        records = []
        for log_file in self._iter_log_files():
            for line in log_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def read_recent_page(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        since_timestamp: float | None = None,
        exclude_event_types: set[str] | None = None,
    ) -> tuple[list[dict], int]:
        filtered_records = []
        for record in reversed(self._iter_records()):
            if since_timestamp is not None and float(record.get("timestamp") or 0) < since_timestamp:
                continue
            if exclude_event_types and str(record.get("event_type") or "") in exclude_event_types:
                continue
            filtered_records.append(record)

        total = len(filtered_records)
        safe_page = max(1, page)
        safe_page_size = max(1, page_size)
        start = (safe_page - 1) * safe_page_size
        end = start + safe_page_size
        return filtered_records[start:end], total

    def summary_by_upstream(self, since_timestamp: float | None = None) -> dict[str, dict]:
        summary: dict[str, dict] = {}
        for record in self._iter_records():
            if since_timestamp is not None and float(record.get("timestamp") or 0) < since_timestamp:
                continue

            upstream = record.get("upstream_name") or "unknown"
            usage = record.get("usage") or {}
            item = summary.setdefault(
                upstream,
                {
                    "request_count": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cached_tokens": 0,
                    "reasoning_tokens": 0,
                    "avg_elapsed_ms": 0,
                    "_elapsed_sum": 0,
                },
            )
            item["request_count"] += 1
            if record.get("success"):
                item["success_count"] += 1
            else:
                item["failure_count"] += 1
            item["input_tokens"] += int(usage.get("input_tokens") or 0)
            item["output_tokens"] += int(usage.get("output_tokens") or 0)
            item["total_tokens"] += int(usage.get("total_tokens") or 0)
            item["cached_tokens"] += int(usage.get("cached_tokens") or 0)
            item["reasoning_tokens"] += int(usage.get("reasoning_tokens") or 0)
            item["_elapsed_sum"] += int(record.get("elapsed_ms") or 0)

        for item in summary.values():
            count = item["request_count"] or 1
            item["avg_elapsed_ms"] = round(item["_elapsed_sum"] / count)
            del item["_elapsed_sum"]
        return summary

    def latest_record(
        self,
        *,
        upstream_name: str | None = None,
        event_type: str | None = None,
    ) -> dict | None:
        for record in reversed(self._iter_records()):
            if upstream_name and str(record.get("upstream_name") or "") != upstream_name:
                continue
            if event_type and str(record.get("event_type") or "") != event_type:
                continue
            return record
        return None
