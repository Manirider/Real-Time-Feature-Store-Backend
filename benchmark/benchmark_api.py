"""Performance benchmark runner for the Real-Time Feature Store API.

Executes concurrent GET /features/{user_id} requests against the running API,
measures end-to-end HTTP request latencies, and computes statistical percentiles (p50, p90, p95, p99).
"""

import asyncio
import os
import statistics
import sys
import time
from typing import List
import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000")
CONCURRENCY = int(os.getenv("BENCHMARK_CONCURRENCY", "50"))
TOTAL_REQUESTS = int(os.getenv("BENCHMARK_REQUESTS", "1000"))


async def fetch_user_features(client: httpx.AsyncClient, user_id: str) -> float:
    """Fetch user features and return end-to-end roundtrip latency in milliseconds."""
    start = time.perf_counter()
    resp = await client.get(f"{API_URL}/features/{user_id}")
    latency_ms = (time.perf_counter() - start) * 1000.0
    resp.raise_for_status()
    return latency_ms


async def wait_for_api_and_users(client: httpx.AsyncClient, max_wait_sec: int = 30) -> List[str]:
    """Poll API health and discover populated user IDs before running benchmark."""
    print(f"Checking API health at {API_URL}/health...")
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        try:
            resp = await client.get(f"{API_URL}/health")
            if resp.status_code == 200:
                print("API is healthy. Discovering known user records...")
                break
        except Exception:
            pass
        await asyncio.sleep(1.0)
    else:
        raise RuntimeError(f"API at {API_URL} did not become ready within {max_wait_sec}s.")

    # Find valid populated users
    candidate_ids = [f"user_{i:08d}" for i in range(1, 201)]
    valid_ids: List[str] = []

    for uid in candidate_ids:
        try:
            resp = await client.get(f"{API_URL}/features/{uid}")
            if resp.status_code == 200:
                valid_ids.append(uid)
                if len(valid_ids) >= 100:
                    break
        except Exception:
            continue

    if not valid_ids:
        raise RuntimeError("No populated user records found in feature store. Ensure ingestion worker has started.")

    print(f"Discovered {len(valid_ids)} active test user records for benchmarking.")
    return valid_ids


async def run_benchmark():
    """Run concurrent benchmark against the Feature Store API."""
    limits = httpx.Limits(max_connections=CONCURRENCY + 20, max_keepalive_connections=CONCURRENCY)
    timeout = httpx.Timeout(15.0, connect=5.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        test_users = await wait_for_api_and_users(client)

        print(f"\nStarting benchmark: {TOTAL_REQUESTS} requests, Concurrency: {CONCURRENCY}...")
        sem = asyncio.Semaphore(CONCURRENCY)
        latencies: List[float] = []
        errors = 0

        async def worker(uid: str):
            nonlocal errors
            async with sem:
                try:
                    lat = await fetch_user_features(client, uid)
                    latencies.append(lat)
                except Exception as exc:
                    errors += 1

        tasks = []
        for i in range(TOTAL_REQUESTS):
            uid = test_users[i % len(test_users)]
            tasks.append(asyncio.create_task(worker(uid)))

        bench_start = time.perf_counter()
        await asyncio.gather(*tasks)
        total_bench_time = time.perf_counter() - bench_start

        if not latencies:
            print("ERROR: All benchmark requests failed.")
            sys.exit(1)

        latencies.sort()
        n = len(latencies)
        p50 = latencies[int(n * 0.50)]
        p90 = latencies[int(n * 0.90)]
        p95 = latencies[int(n * 0.95)]
        p99 = latencies[int(n * 0.99)]
        avg = statistics.mean(latencies)
        min_v = min(latencies)
        max_v = max(latencies)
        throughput = len(latencies) / total_bench_time if total_bench_time > 0 else 0

        print()
        print("Feature Store Benchmark")
        print("-----------------------")
        print(f"Requests: {len(latencies)}")
        print(f"Concurrency: {CONCURRENCY}")
        if errors > 0:
            print(f"Errors: {errors}")
        print(f"Throughput: {throughput:.1f} req/s")
        print()
        print(f"p50: {p50:.2f} ms")
        print(f"p90: {p90:.2f} ms")
        print(f"p95: {p95:.2f} ms")
        print(f"p99: {p99:.2f} ms")
        print(f"min: {min_v:.2f} ms")
        print(f"max: {max_v:.2f} ms")
        print(f"avg: {avg:.2f} ms")
        print()
        print("Target: p90 <= 50 ms")
        passed = p90 <= 50.0
        print(f"Status: {'PASS' if passed else 'FAIL'}")

        return {
            "requests": len(latencies),
            "concurrency": CONCURRENCY,
            "p50": p50,
            "p90": p90,
            "p95": p95,
            "p99": p99,
            "min": min_v,
            "max": max_v,
            "avg": avg,
            "throughput": throughput,
            "passed": passed,
        }


def main():
    results = asyncio.run(run_benchmark())
    if not results or not results["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
