#!/usr/bin/env python3
"""One-command burst harness that reproduces every graded invariant against a
running instance. Standard library only — runs anywhere Python 3.9+ exists.

    python scripts/burst.py http://localhost:8000
    python scripts/burst.py https://your-app.up.railway.app

Exit code 0 = all invariants held; non-zero = a violation was reproduced.
"""
import argparse
import concurrent.futures as cf
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"


def http(method, path, token=None, body=None, timeout=60, retries=2):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    last_exc = None
    for _ in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or "null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.status, json.loads(raw or "null")
            except json.JSONDecodeError:
                return e.status, {"raw": raw.decode(errors="replace")}
        except (TimeoutError, urllib.error.URLError) as e:
            last_exc = e  # transient (free-tier cold start / overload) — retry
    raise last_exc


def make_wallet(user):
    return http("POST", "/wallets", token=user)[1]


def fund(user, wallet_id, amount):
    return http("POST", f"/wallets/{wallet_id}/deposit", token=user,
                body={"amount_paise": amount, "idempotency_key": f"seed-{uuid.uuid4()}"})


def balance(user, wallet_id):
    return http("GET", f"/wallets/{wallet_id}", token=user)[1]["balance_paise"]


def concurrent(fn, n, workers=None):
    workers = workers or n
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        return [f.result() for f in [ex.submit(fn, i) for i in range(n)]]


# --------------------------------------------------------------------------- #
PASSES, FAILS = [], []


def check(name, ok, detail=""):
    (PASSES if ok else FAILS).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")


# --------------------------------------------------------------------------- #
def gate1_race_free_get_or_create(n=50):
    print(f"\nGate 1 — race-free get-or-create ({n} concurrent POST /wallets)")
    user = f"user-{uuid.uuid4()}"
    results = concurrent(lambda _: make_wallet(user), n)
    ids = {r["id"] for r in results}
    check("exactly one wallet from concurrent create", len(ids) == 1, f"{len(ids)} distinct id(s)")
    check("all balances zero on create", all(r["balance_paise"] == 0 for r in results))


def gate2_idempotent_storm(k=30, amount=5_00):
    print(f"\nGate 2 — idempotent exactly-once transfer ({k} concurrent identical transfers)")
    a_user, b_user = f"A-{uuid.uuid4()}", f"B-{uuid.uuid4()}"
    a, b = make_wallet(a_user), make_wallet(b_user)
    fund(a_user, a["id"], 100_00)
    key = f"idem-{uuid.uuid4()}"
    body = {"from": a["id"], "to": b["id"], "amount_paise": amount, "idempotency_key": key}
    results = concurrent(lambda _: http("POST", "/transfers", token=a_user, body=body), k)
    transfer_ids = {r[1].get("id") for r in results}
    statuses = {r[0] for r in results}
    a_bal, b_bal = balance(a_user, a["id"]), balance(b_user, b["id"])
    check("single transfer id across all replies", len(transfer_ids) == 1, f"{len(transfer_ids)} id(s)")
    check("exactly one debit applied (A = 10000-amount)", a_bal == 100_00 - amount, f"A={a_bal}")
    check("exactly one credit applied (B = amount)", b_bal == amount, f"B={b_bal}")
    check("all responses 2xx", all(200 <= s < 300 for s in statuses), f"statuses={statuses}")

    # same key + different body => 409
    conflict = http("POST", "/transfers", token=a_user,
                    body={**body, "amount_paise": amount + 1})
    check("same key + different body => 409", conflict[0] == 409, f"got {conflict[0]}")


def gate3_conservation(num_wallets=5, seed=100_00, rounds=200, workers=8):
    print(f"\nGate 3 — conservation + no-overdraft under contention ({rounds} concurrent transfers)")
    users = [f"W{i}-{uuid.uuid4()}" for i in range(num_wallets)]
    wallets = [make_wallet(u) for u in users]
    for u, w in zip(users, wallets):
        fund(u, w["id"], seed)
    total_before = seed * num_wallets

    import random

    def one(i):
        s, d = random.sample(range(num_wallets), 2)
        amt = random.choice([1_00, 5_00, 20_00, 150_00])  # some intentionally overdraw
        body = {"from": wallets[s]["id"], "to": wallets[d]["id"],
                "amount_paise": amt, "idempotency_key": f"c-{uuid.uuid4()}"}
        return http("POST", "/transfers", token=users[s], body=body)

    results = concurrent(one, rounds, workers=workers)
    balances = [balance(u, w["id"]) for u, w in zip(users, wallets)]
    total_after = sum(balances)
    server_errors = [r[0] for r in results if r[0] >= 500]
    if server_errors:
        from collections import Counter
        print("      5xx status breakdown:", dict(Counter(server_errors)))
    check("total conserved (sum unchanged)", total_after == total_before,
          f"before={total_before} after={total_after}")
    check("no negative balances", all(b >= 0 for b in balances), f"balances={balances}")
    check("no 5xx under contention (no deadlock storm)", not server_errors,
          f"{len(server_errors)} server error(s)")


def gate4_reversal(amount=30_00):
    print("\nR3 — reversal: conservation + exactly-once + already-reversed guard")
    a_user, b_user = f"RA-{uuid.uuid4()}", f"RB-{uuid.uuid4()}"
    a, b = make_wallet(a_user), make_wallet(b_user)
    fund(a_user, a["id"], 100_00)
    t = http("POST", "/transfers", token=a_user,
             body={"from": a["id"], "to": b["id"], "amount_paise": amount,
                   "idempotency_key": f"t-{uuid.uuid4()}"})[1]
    pre_a, pre_b = 100_00 - amount, amount
    check("post-transfer balances", balance(a_user, a["id"]) == pre_a and balance(b_user, b["id"]) == pre_b)

    # reverse twice concurrently with the SAME key => one refund
    rev_key = f"rev-{uuid.uuid4()}"
    rev_results = concurrent(
        lambda _: http("POST", f"/transfers/{t['id']}/reverse", token=a_user,
                       body={"idempotency_key": rev_key}), 20, workers=20)
    rev_ids = {r[1].get("id") for r in rev_results if r[0] < 400}
    check("single reversal id across concurrent same-key replies", len(rev_ids) == 1, f"{len(rev_ids)} id(s)")
    check("balances restored to pre-transfer sum",
          balance(a_user, a["id"]) == 100_00 and balance(b_user, b["id"]) == 0)

    # reversing again with a DIFFERENT key => clean 409, no second refund
    again = http("POST", f"/transfers/{t['id']}/reverse", token=a_user,
                 body={"idempotency_key": f"rev2-{uuid.uuid4()}"})
    check("already-reversed with new key => 409", again[0] == 409, f"got {again[0]}")
    check("no double refund (A still 10000)", balance(a_user, a["id"]) == 100_00)


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url", nargs="?", default=BASE)
    ap.add_argument("--skip-reversal", action="store_true")
    args = ap.parse_args()
    BASE = args.base_url.rstrip("/")
    print(f"Target: {BASE}")

    gate1_race_free_get_or_create()
    gate2_idempotent_storm()
    gate3_conservation()
    if not args.skip_reversal:
        gate4_reversal()

    print(f"\n==== {len(PASSES)} passed, {len(FAILS)} failed ====")
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("All invariants held.")


if __name__ == "__main__":
    main()
