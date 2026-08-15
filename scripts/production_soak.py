from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _request_json(
    *,
    base_url: str,
    path: str,
    method: str,
    token: str | None,
    timeout_seconds: float,
) -> tuple[int, dict, float]:
    headers = {"Accept": "application/json"}
    data = None
    if method == "POST":
        data = b"{}"
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-DecisionVault-Token"] = token
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    started = time.monotonic()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            raw = response.read(2 * 1024 * 1024)
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read(2 * 1024 * 1024)
    latency_ms = (time.monotonic() - started) * 1000.0
    payload = json.loads(raw) if raw else {}
    if not isinstance(payload, dict):
        raise RuntimeError("soak endpoint returned a non-object JSON payload")
    return status, payload, latency_ms


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Low-rate DecisionVault production soak using readiness and the two "
            "self-cleaning judge workflows. It deliberately avoids /decide so "
            "the soak does not pollute long-term calibration telemetry."
        )
    )
    parser.add_argument("--base-url-file", type=Path, required=True)
    parser.add_argument("--demo-token-file", type=Path, required=True)
    parser.add_argument("--duration-minutes", type=float, default=30.0)
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=float, default=25.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/production-soak.json"),
    )
    args = parser.parse_args()
    if args.duration_minutes <= 0:
        raise SystemExit("duration-minutes must be positive")
    if args.interval_seconds < 6.0:
        raise SystemExit("interval-seconds must be >= 6 to respect judge rate limits")

    base_url = args.base_url_file.read_text(encoding="utf-8").strip().rstrip("/")
    token = args.demo_token_file.read_text(encoding="utf-8").strip()
    if not base_url or not token:
        raise SystemExit("base URL and demo token are required")

    started_at = datetime.now(timezone.utc)
    deadline = time.monotonic() + args.duration_minutes * 60.0
    latencies: dict[str, list[float]] = {
        "/health/ready": [],
        "/demo": [],
        "/governance-demo": [],
    }
    status_counts: dict[str, dict[str, int]] = {path: {} for path in latencies}
    validation_failures: list[str] = []
    transport_failures = 0
    iteration = 0

    while time.monotonic() < deadline:
        cycle_started = time.monotonic()
        path = "/demo" if iteration % 2 == 0 else "/governance-demo"
        for current_path, method, current_token in (
            ("/health/ready", "GET", None),
            (path, "POST", token),
        ):
            try:
                status, payload, latency_ms = _request_json(
                    base_url=base_url,
                    path=current_path,
                    method=method,
                    token=current_token,
                    timeout_seconds=args.timeout_seconds,
                )
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                transport_failures += 1
                validation_failures.append(
                    f"{current_path}:transport:{type(exc).__name__}"
                )
                continue
            latencies[current_path].append(latency_ms)
            bucket = status_counts[current_path]
            bucket[str(status)] = bucket.get(str(status), 0) + 1
            if current_path == "/health/ready":
                if status != 200 or payload.get("status") != "ready" or payload.get("errors"):
                    validation_failures.append("readiness_not_ready")
            elif current_path == "/demo":
                if not (
                    status == 200
                    and bool(payload.get("expected_change"))
                    and bool(payload.get("cross_agent_memory_used"))
                    and bool(payload.get("cleaned"))
                ):
                    validation_failures.append("demo_contract_failed")
            else:
                decision = payload.get("decision") or {}
                if not (
                    status == 200
                    and bool(payload.get("expected_abstention"))
                    and decision.get("action") == "ABSTAIN"
                    and decision.get("executable") is False
                    and decision.get("memory_resolution") == "CONFLICT_ABSTAIN"
                    and bool(payload.get("cleaned"))
                ):
                    validation_failures.append("governance_contract_failed")

        iteration += 1
        remaining = args.interval_seconds - (time.monotonic() - cycle_started)
        if remaining > 0 and time.monotonic() < deadline:
            time.sleep(min(remaining, max(0.0, deadline - time.monotonic())))

    all_latencies = [value for values in latencies.values() for value in values]
    payload = {
        "duration_minutes": args.duration_minutes,
        "interval_seconds": args.interval_seconds,
        "iterations": iteration,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status_counts": status_counts,
        "transport_failures": transport_failures,
        "validation_failure_count": len(validation_failures),
        "validation_failure_types": sorted(set(validation_failures)),
        "latency_ms": {
            "overall": {
                "count": len(all_latencies),
                "p50": _percentile(all_latencies, 0.50),
                "p95": _percentile(all_latencies, 0.95),
                "p99": _percentile(all_latencies, 0.99),
                "mean": round(statistics.fmean(all_latencies), 3)
                if all_latencies
                else None,
            },
            **{
                path: {
                    "count": len(values),
                    "p50": _percentile(values, 0.50),
                    "p95": _percentile(values, 0.95),
                    "p99": _percentile(values, 0.99),
                }
                for path, values in latencies.items()
            },
        },
        "passed": not validation_failures and transport_failures == 0,
        "telemetry_pollution_avoided": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"soak_duration_minutes={args.duration_minutes}")
    print(f"soak_iterations={iteration}")
    print(f"soak_transport_failures={transport_failures}")
    print(f"soak_validation_failures={len(validation_failures)}")
    print(f"soak_p95_ms={payload['latency_ms']['overall']['p95']}")
    print(f"production_soak={'PASS' if payload['passed'] else 'FAIL'}")
    return 0 if payload["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
