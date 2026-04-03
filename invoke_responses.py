import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def build_body(args: argparse.Namespace) -> dict:
    messages = []

    if args.system_prompt:
        messages.append(
            {
                "role": "system",
                "content": [{"type": "input_text", "text": args.system_prompt}],
            }
        )

    messages.append(
        {
            "role": "user",
            "content": [{"type": "input_text", "text": args.input}],
        }
    )

    return {
        "model": args.model,
        "input": messages,
        "reasoning": {"effort": args.reasoning_effort},
        "text": {"verbosity": args.verbosity},
    }


def extract_json_from_data_line(line: str) -> dict | None:
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8327/v1/responses")
    parser.add_argument("--api-key", default="codex-proxy-key")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--input", default="Say ping")
    parser.add_argument("--system-prompt", default="")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--verbosity", default="medium")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--show-events", action="store_true")
    args = parser.parse_args()

    body = json.dumps(build_body(args)).encode("utf-8")
    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {args.api_key}",
        },
    )

    started = time.perf_counter()
    first_event_ms = None
    completed_ms = None
    final_text_parts: list[str] = []
    status = None

    try:
        with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
            status = response.status
            headers_ms = round((time.perf_counter() - started) * 1000)

            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue

                if args.show_events:
                    print(line)

                if first_event_ms is None and line.startswith("event:"):
                    first_event_ms = round((time.perf_counter() - started) * 1000)

                payload = extract_json_from_data_line(line)
                if not payload:
                    continue

                payload_type = payload.get("type")
                if payload_type == "response.output_text.delta":
                    delta = payload.get("delta")
                    if isinstance(delta, str):
                        final_text_parts.append(delta)
                elif payload_type == "response.output_text.done":
                    text = payload.get("text")
                    if isinstance(text, str):
                        final_text_parts = [text]
                elif payload_type == "response.completed":
                    completed_ms = round((time.perf_counter() - started) * 1000)
                    break

    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        print(f"STATUS={exc.code}")
        print("ERROR_START")
        print(body_text)
        print("ERROR_END")
        return 1
    except Exception as exc:
        print("STATUS=CLIENT_ERROR")
        print("ERROR_START")
        print(str(exc))
        print("ERROR_END")
        return 1

    if completed_ms is None:
        completed_ms = round((time.perf_counter() - started) * 1000)

    final_text = "".join(final_text_parts)

    print(f"STATUS={status}")
    print(f"HEADERS_MS={headers_ms}")
    print(f"FIRST_EVENT_MS={first_event_ms}")
    print(f"COMPLETED_MS={completed_ms}")
    print("FINAL_TEXT_START")
    print(final_text)
    print("FINAL_TEXT_END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
