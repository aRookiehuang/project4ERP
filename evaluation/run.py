"""HTTP regression/load evaluator. Browser complete latency is measured separately by browser_smoke.py."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import time
import uuid
from collections import Counter
from pathlib import Path

import httpx


def matches(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and matches(actual[k], v) for k, v in expected.items()
        )
    if isinstance(expected, list):
        # Ordered rows are compared as arrays. Unordered rows use a multiset, not a set.
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(matches(a, e) for a, e in zip(actual, expected))
        )
    return actual == expected


def equivalent(actual, expected, ordered=True):
    if ordered:
        return matches(actual, expected)
    return Counter(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in actual) == Counter(
        json.dumps(r, ensure_ascii=False, sort_keys=True) for r in expected
    )


def summarize(attempts):
    count = len(attempts)
    completed = sorted(a["http_ms"] if a["completed"] else math.inf for a in attempts)
    p95 = completed[max(0, math.ceil(count * 0.95) - 1)] if count else math.inf
    return {
        "attempts": count,
        "correct": sum(a["correct"] for a in attempts),
        "accuracy": sum(a["correct"] for a in attempts) / count if count else 0,
        "joint_correct_http_under_3s": sum(a["correct"] and a["http_ms"] <= 3000 for a in attempts) / count
        if count
        else 0,
        "http_p95_ms": p95 if math.isfinite(p95) else None,
        "http_p95_incomplete": not math.isfinite(p95),
        "failures": [a for a in attempts if not a["correct"]],
    }


async def evaluate(args):
    raw = Path(args.cases).read_bytes()
    cases = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(base_url=args.url, timeout=20) as auth_client:
        login = await auth_client.post(
            "/api/auth/login",
            json={
                "username": args.username,
                "password": os.environ.get("ERP_EVAL_PASSWORD", "erp-demo-2026"),
            },
        )
        login.raise_for_status()
        csrf = login.json()["csrf_token"]
        cookies = dict(auth_client.cookies)

    async def attempt(case, number):
        async with semaphore, httpx.AsyncClient(base_url=args.url, timeout=20) as client:
            client.cookies.update(cookies)
            client.headers["X-CSRF-Token"] = csrf
            conv = (
                await client.post("/api/conversations", json={"title": "评测 " + case["case_id"]})
            ).json()["id"]
            started = time.perf_counter()
            correct, completed, code = True, True, None
            timings = []
            try:
                for turn in case["turns"]:
                    begin = time.perf_counter()
                    response = await client.post(
                        f"/api/conversations/{conv}/queries",
                        json={"question": turn["question"], "idempotency_key": str(uuid.uuid4())},
                    )
                    data = response.json()
                    timings.append((time.perf_counter() - begin) * 1000)
                    completed &= response.is_success and data.get("status") == "success"
                    expected = turn["expected"]
                    correct &= matches(data, {k: v for k, v in expected.items() if k != "rows"})
                    if "rows" in expected:
                        rows = list(data.get("rows", []))
                        if data.get("result_id"):
                            for page in range(2, math.ceil(data["total_rows"] / data["page_size"]) + 1):
                                rows.extend(
                                    (
                                        await client.get(f"/api/results/{data['result_id']}?page={page}")
                                    ).json()["rows"]
                                )
                        correct &= equivalent(rows, expected["rows"], turn.get("ordered", True))
                    code = data.get("code")
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                correct, completed, code = False, False, type(exc).__name__
            return {
                "case_id": case["case_id"],
                "attempt": number,
                "category": case.get("category", "unspecified"),
                "correct": correct,
                "completed": completed,
                "code": code,
                "http_ms": round((time.perf_counter() - started) * 1000, 2),
                "turn_http_ms": timings,
            }

    attempts = await asyncio.gather(*(attempt(case, n) for n in range(args.repeat) for case in cases))
    return {
        "kind": "development HTTP regression; NOT formal blind acceptance or browser latency",
        "cases_sha256": hashlib.sha256(raw).hexdigest(),
        "concurrency": args.concurrency,
        "application_cache": "disabled (not implemented)",
        **summarize(attempts),
        "details": attempts,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cases")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="demo")
    parser.add_argument("--concurrency", type=int, choices=[1, 5], default=1)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", default="artifacts/evaluation.json")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat must be positive")
    report = asyncio.run(evaluate(args))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"details", "failures"}},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
