#!/usr/bin/env python3
"""Standard-library assessment harness. No automatic HTTP retries; exit 1 on failure."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import random
import threading
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"
RUN_ID = f"assessment-{uuid.uuid4().hex}"
REQUESTS = []
REQUEST_LOCK = threading.Lock()
PASSES, FAILS = [], []


def http(method, path, token=None, body=None, timeout=120):
    request_id = f"{RUN_ID}-{uuid.uuid4().hex}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Request-ID", request_id)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    started = time.perf_counter()
    status, echoed_id = 0, None
    try:
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.status
            echoed_id = response.headers.get("x-request-id")
            raw = response.read()
        try:
            result = json.loads(raw or "null")
        except json.JSONDecodeError:
            result = {"raw": raw.decode(errors="replace")}
        return status, result
    except (TimeoutError, OSError, urllib.error.URLError) as error:
        return 0, {"error": type(error).__name__}
    finally:
        with REQUEST_LOCK:
            REQUESTS.append({"request_id": request_id, "method": method, "path": path,
                             "status": status, "correlation_matches": echoed_id == request_id,
                             "latency_ms": round((time.perf_counter() - started) * 1000, 3)})


def make_wallet(user):
    status, result = http("POST", "/wallets", user)
    if status != 200 or not isinstance(result, dict) or "id" not in result:
        raise RuntimeError(f"wallet creation failed: HTTP {status}")
    return result


def fund(user, wallet_id, amount):
    response = http("POST", f"/wallets/{wallet_id}/deposit", user,
                    {"amount_paise": amount, "idempotency_key": f"seed-{uuid.uuid4()}"})
    if response[0] != 201 or response[1].get("status") != "completed":
        raise RuntimeError(f"funding failed: HTTP {response[0]}")
    return response


def balance(user, wallet_id):
    status, result = http("GET", f"/wallets/{wallet_id}", user)
    if status != 200:
        raise RuntimeError(f"balance read failed: HTTP {status}")
    return result["balance_paise"]


def concurrent(operation, count, workers=None):
    with ThreadPoolExecutor(max_workers=workers or count) as executor:
        futures = [executor.submit(operation, index) for index in range(count)]
        return [future.result() for future in futures]


def check(name, passed, detail=""):
    (PASSES if passed else FAILS).append(name)
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def transfer_body(source, destination, amount, key=None):
    return {"from": source["id"], "to": destination["id"], "amount_paise": amount,
            "idempotency_key": key or str(uuid.uuid4())}


def gate1_race_free_get_or_create():
    print("\nGate 1: 50 simultaneous fresh-user creates")
    user = f"create-{uuid.uuid4()}"
    results = concurrent(lambda _: make_wallet(user), 50)
    check("exactly one wallet", len({result["id"] for result in results}) == 1)
    check("all initial balances zero", all(result["balance_paise"] == 0 for result in results))


def gate2_idempotent_storm():
    print("\nGate 2: 30 simultaneous identical transfers")
    sender, receiver = f"sender-{uuid.uuid4()}", f"receiver-{uuid.uuid4()}"
    source, destination = make_wallet(sender), make_wallet(receiver)
    fund(sender, source["id"], 10000)
    body = transfer_body(source, destination, 500)
    results = concurrent(lambda _: http("POST", "/transfers", sender, body), 30)
    check("all transfer replies succeed", all(status in (200, 201) for status, _ in results))
    check("one newly created transfer", sum(status == 201 for status, _ in results) == 1)
    check("all replay bodies identical", all(result == results[0][1] for _, result in results))
    check("exactly one debit and credit", balance(sender, source["id"]) == 9500
          and balance(receiver, destination["id"]) == 500)
    stored = http("GET", f"/transfers/{results[0][1].get('id')}", sender)
    check("GET matches recorded result", stored == (200, results[0][1]))
    conflict = http("POST", "/transfers", sender, {**body, "amount_paise": 501})
    check("same key different body returns 409", conflict[0] == 409)


def gate3_conservation():
    print("\nGate 3: 300 contending transfers, 40 workers, five wallets")
    users = [f"contention-{uuid.uuid4()}" for _ in range(5)]
    wallets = [make_wallet(user) for user in users]
    for user, wallet in zip(users, wallets):
        fund(user, wallet["id"], 10000)
    generator = random.Random(42)
    workload = [(index % 2, 1 - index % 2, 100) for index in range(100)]
    for _ in range(200):
        source, destination = generator.sample(range(5), 2)
        workload.append((source, destination, generator.choice([100, 500, 2000, 15000])))

    def one(index):
        source, destination, amount = workload[index]
        return http("POST", "/transfers", users[source],
                    transfer_body(wallets[source], wallets[destination], amount))

    results = concurrent(one, 300, workers=40)
    balances = [balance(user, wallet["id"]) for user, wallet in zip(users, wallets)]
    check("total conserved", sum(balances) == 50000, f"sum={sum(balances)}")
    check("no negative balances", all(value >= 0 for value in balances), str(balances))
    check("no server or transport errors", all(0 < status < 500 for status, _ in results),
          str(dict(Counter(status for status, _ in results))))
    check("every request records completed or declined", all(
        status == 201 and result.get("status") in {"completed", "declined"} for status, result in results))
    expected = [10000] * 5
    for (source, destination, amount), (_, result) in zip(workload, results):
        if result.get("status") == "completed":
            expected[source] -= amount
            expected[destination] += amount
    check("balances reconcile to completed ledger", balances == expected)


def gate4_reversal():
    print("\nR3: same-key replay, different-key guard, insufficient recipient funds")
    sender, receiver = f"reversal-a-{uuid.uuid4()}", f"reversal-b-{uuid.uuid4()}"
    source, destination = make_wallet(sender), make_wallet(receiver)
    fund(sender, source["id"], 10000)
    original = http("POST", "/transfers", sender, transfer_body(source, destination, 3000))[1]
    path = f"/transfers/{original['id']}/reverse"
    body = {"idempotency_key": f"reverse-{uuid.uuid4()}"}
    results = concurrent(lambda _: http("POST", path, sender, body), 20)
    check("every reversal succeeds with identical body", all(
        status in (200, 201) and result == results[0][1] for status, result in results)
        and sum(status == 201 for status, _ in results) == 1)
    check("reversal restores balances", balance(sender, source["id"]) == 10000
          and balance(receiver, destination["id"]) == 0)
    check("different-key second reversal returns 409",
          http("POST", path, sender, {"idempotency_key": str(uuid.uuid4())})[0] == 409)
    original = http("POST", "/transfers", sender, transfer_body(source, destination, 100))[1]
    http("POST", "/transfers", receiver, transfer_body(destination, source, 100))
    path = f"/transfers/{original['id']}/reverse"
    declined = http("POST", path, sender, body := {"idempotency_key": str(uuid.uuid4())})
    check("spent funds cause persisted reversal decline", declined[0] == 201
          and declined[1].get("decline_reason") == "recipient_insufficient_funds"
          and http("POST", path, sender, body) == (200, declined[1])
          and balance(sender, source["id"]) == 10000 and balance(receiver, destination["id"]) == 0)


def gate5_edges():
    print("\nEdge cases: strict amounts, authorization, overflow, deposit replay")
    sender, receiver = f"edge-a-{uuid.uuid4()}", f"edge-b-{uuid.uuid4()}"
    source, destination = make_wallet(sender), make_wallet(receiver)
    body = transfer_body(source, destination, 1)
    invalid_responses = [http("POST", path, sender, {**body, "amount_paise": amount})
                         for path in ("/transfers", f"/wallets/{source['id']}/deposit")
                         for amount in (True, False, 1.0, "1", 0, -1, 1.5, 2**63)]
    check("invalid money rejected on both endpoints", all(status == 422 for status, _ in invalid_responses))
    check("missing authentication rejected", http("POST", "/wallets")[0] == 401)
    check("unauthorized debit rejected", http("POST", "/transfers", receiver, body)[0] == 403)
    check("unauthorized deposit rejected", http("POST", f"/wallets/{source['id']}/deposit", receiver, body)[0] == 403)
    check("wallet reads owner-only", http("GET", f"/wallets/{source['id']}", receiver)[0] == 403)
    declined = http("POST", "/transfers", sender, body)
    path = f"/transfers/{declined[1].get('id')}"
    check("transfer reads participant-only", http("GET", path, "unrelated-reader")[0] == 403
          and http("GET", path, receiver)[0] == 200)
    fund(sender, source["id"], 10)
    check("decline stays idempotent after funding", declined[0] == 201
          and declined[1].get("status") == "declined"
          and http("POST", "/transfers", sender, body) == (200, declined[1]))
    maximum = 2**63 - 1
    fund(receiver, destination["id"], maximum)
    overflow_body = transfer_body(source, destination, 1)
    overflow = http("POST", "/transfers", sender, overflow_body)
    deposit_overflow = http("POST", f"/wallets/{destination['id']}/deposit", receiver,
                            {"amount_paise": 1, "idempotency_key": str(uuid.uuid4())})
    check("overflow returns 409 with no partial debit", overflow[0] == deposit_overflow[0] == 409
          and balance(sender, source["id"]) == 10 and balance(receiver, destination["id"]) == maximum)
    drain = http("POST", "/transfers", receiver, transfer_body(destination, source, 1))
    retried = http("POST", "/transfers", sender, overflow_body)
    check("overflow rolls back idempotency claim", drain[0] == retried[0] == 201)
    deposit_body = {"amount_paise": 1, "idempotency_key": str(uuid.uuid4())}
    deposited = http("POST", f"/wallets/{source['id']}/deposit", sender, deposit_body)
    replayed = http("POST", f"/wallets/{source['id']}/deposit", sender, deposit_body)
    check("deposit replay applies once", deposited[0] == 201 and replayed == (200, deposited[1])
          and balance(sender, source["id"]) == 11)


def gate6_mixed_reversals():
    print("\nMixed opposing transfers and different-key reversals: 40 workers")
    users = [f"mixed-{uuid.uuid4()}" for _ in range(2)]
    wallets = [make_wallet(user) for user in users]
    for user, wallet in zip(users, wallets):
        fund(user, wallet["id"], 10000)
    originals = [http("POST", "/transfers", users[0], transfer_body(wallets[0], wallets[1], 1))[1]
                 for _ in range(20)]

    def one(index):
        if index < 40:
            original = originals[index // 2]
            return http("POST", f"/transfers/{original['id']}/reverse", users[0],
                        {"idempotency_key": str(uuid.uuid4())})
        source = index % 2
        return http("POST", "/transfers", users[source], transfer_body(wallets[source], wallets[1 - source], 1))

    results = concurrent(one, 100, workers=40)
    check("exactly one different-key reversal per original", sum(status == 201 for status, _ in results[:40]) == 20
          and sum(status == 409 and result.get("error") == "already_reversed" for status, result in results[:40]) == 20)
    check("all mixed transfers complete", all(status == 201 and result.get("status") == "completed"
                                             for status, result in results[40:]))
    check("mixed traffic balances reconcile exactly",
          [balance(user, wallet["id"]) for user, wallet in zip(users, wallets)] == [10000, 10000])


def capture_metrics():
    try:
        with urllib.request.urlopen(BASE + "/metrics", timeout=120) as response:
            return response.read().decode()
    except (urllib.error.URLError, OSError) as error:
        detail = f"HTTP {error.code}" if isinstance(error, urllib.error.HTTPError) else type(error).__name__
        check("metrics snapshot available", False, detail)
        return f"# Metrics unavailable: {detail}\n"


def write_evidence(directory, elapsed, before_metrics, revision):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    after_metrics = capture_metrics()
    latencies = sorted(record["latency_ms"] for record in REQUESTS)
    errors = sum(record["status"] == 0 or record["status"] >= 500 for record in REQUESTS)
    summary = {"target": BASE, "revision": revision, "run_id": RUN_ID, "passed": PASSES, "failed": FAILS,
               "requests": len(REQUESTS), "duration_seconds": round(elapsed, 3),
               "request_rate_per_second": round(len(REQUESTS) / elapsed, 3),
               "p99_client_latency_ms": latencies[max(0, math.ceil(len(latencies) * 0.99) - 1)] if latencies else None,
               "server_or_transport_errors": errors, "error_rate": errors / len(REQUESTS) if REQUESTS else None,
               "latency_scope": "Client HTTP timings including network; expected 4xx are not server errors",
               "http_retries": 0}
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (directory / "requests.jsonl").write_text("".join(json.dumps(record) + "\n" for record in REQUESTS), encoding="utf-8")
    (directory / "metrics-before.txt").write_text(before_metrics, encoding="utf-8")
    (directory / "metrics-after.txt").write_text(after_metrics, encoding="utf-8")
    print(f"Evidence: {directory}; client p99={summary['p99_client_latency_ms']}ms; server/transport errors={errors}")


def main():
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", nargs="?", default=BASE)
    parser.add_argument("--skip-reversal", action="store_true")
    parser.add_argument("--evidence-dir")
    args = parser.parse_args()
    BASE = args.base_url.rstrip("/")
    print(f"Target: {BASE}")
    before_metrics = capture_metrics() if args.evidence_dir else ""
    started = time.perf_counter()
    revision = http("GET", "/")[1].get("revision", "unknown")
    try:
        gate1_race_free_get_or_create()
        gate2_idempotent_storm()
        gate3_conservation()
        gate5_edges()
        if not args.skip_reversal:
            gate4_reversal()
            gate6_mixed_reversals()
        check("all responses preserve correlation IDs", all(record["correlation_matches"] for record in REQUESTS))
    except Exception as error:
        check("harness completed", False, f"{type(error).__name__}: {error}")
    finally:
        if args.evidence_dir:
            write_evidence(args.evidence_dir, time.perf_counter() - started, before_metrics, revision)
    print(f"\n==== {len(PASSES)} passed, {len(FAILS)} failed ====")
    if FAILS:
        raise SystemExit(1)
    print("All invariants held.")


if __name__ == "__main__":
    main()