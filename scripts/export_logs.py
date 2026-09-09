"""Export an allowlisted, assessment-run-only JSON log capture for public sharing."""
import argparse
import json
from pathlib import Path
import re
import uuid


EVENTS = {
    "wallet.created", "deposit.applied", "deposit.idempotent_replay",
    "transfer.debited", "transfer.credited", "transfer.created", "transfer.declined",
    "transfer.idempotent_replay", "reversal.created", "reversal.declined",
    "reversal.idempotent_replay", "http.access", "request.error",
}
PATHS = {"/", "/healthz", "/wallets", "/wallets/{wallet_id}", "/wallets/{wallet_id}/deposit",
         "/transfers", "/transfers/{transfer_id}", "/transfers/{transfer_id}/reverse", "unmatched"}


def sanitize(line, run_id):
    try:
        record = json.loads(line[line.index("{"):])
    except (ValueError, json.JSONDecodeError):
        return None
    event = record.get("event")
    request_id = record.get("correlation_id", "")
    if event not in EVENTS or not re.fullmatch(re.escape(run_id) + r"-[a-f0-9]{32}", request_id):
        return None
    result = {"event": event, "correlation_id": request_id}
    timestamp = record.get("ts", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", timestamp):
        result["ts"] = timestamp
    for field in ("wallet_id", "transfer_id", "from_wallet", "to_wallet", "reverses"):
        try:
            result[field] = str(uuid.UUID(record[field]))
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
    for field in ("amount_paise", "latency_ms", "status"):
        if type(record.get(field)) in (int, float):
            result[field] = record[field]
    if record.get("path") in PATHS:
        result["path"] = record["path"]
    if record.get("method") in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "OTHER"}:
        result["method"] = record["method"]
    if record.get("reason") in {"insufficient_funds", "recipient_insufficient_funds"}:
        result["reason"] = record["reason"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_log")
    parser.add_argument("evidence_dir")
    args = parser.parse_args()
    directory = Path(args.evidence_dir)
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    records = [result for line in Path(args.raw_log).read_text(encoding="utf-8-sig").splitlines()
               if (result := sanitize(line, summary["run_id"])) is not None]
    (directory / "service.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    requests = [json.loads(line) for line in (directory / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    access_ids = {record["correlation_id"] for record in records if record["event"] == "http.access"}
    missing = {record["request_id"] for record in requests} - access_ids
    print(f"Exported {len(records)} sanitized events; {len(missing)} request logs missing")
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()