import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CheckResult:
    path: str
    status_code: int
    passed: bool


def request_json(base_url: str, path: str, *, api_key: str | None) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def verify(base_url: str, *, attempts: int, delay_seconds: float) -> list[CheckResult]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            live_status, live = request_json(base_url, "/health/live", api_key=None)
            ready_status, ready = request_json(base_url, "/health/ready", api_key=None)
            schema_status, schema = request_json(base_url, "/openapi.json", api_key=None)
            results = [
                CheckResult(
                    path="/health/live",
                    status_code=live_status,
                    passed=live_status == 200
                    and isinstance(live, dict)
                    and live.get("status") == "alive",
                ),
                CheckResult(
                    path="/health/ready",
                    status_code=ready_status,
                    passed=ready_status == 200
                    and isinstance(ready, dict)
                    and ready.get("status") == "ready",
                ),
                CheckResult(
                    path="/openapi.json",
                    status_code=schema_status,
                    passed=schema_status == 200
                    and isinstance(schema, dict)
                    and schema.get("info", {}).get("title") == "ResolveOps API",
                ),
            ]
            if all(item.passed for item in results):
                return results
            last_error = RuntimeError("one or more deployment checks failed")
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(delay_seconds)
    raise RuntimeError(f"deployment verification failed after {attempts} attempts") from last_error


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a deployed ResolveOps API")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--attempts", type=int, default=20)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    arguments = parser.parse_args()
    if arguments.attempts <= 0 or arguments.delay_seconds < 0:
        parser.error("attempts must be positive and delay-seconds cannot be negative")
    results = verify(
        arguments.base_url,
        attempts=arguments.attempts,
        delay_seconds=arguments.delay_seconds,
    )
    print(json.dumps({"status": "verified", "checks": [asdict(item) for item in results]}))


if __name__ == "__main__":
    main()
