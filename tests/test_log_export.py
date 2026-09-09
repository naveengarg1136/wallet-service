import json
import unittest

from scripts.export_logs import sanitize


class LogExportTests(unittest.TestCase):
    def test_export_drops_credentials_and_unrelated_requests(self):
        run_id = "assessment-" + "a" * 32
        record = {"event": "http.access", "correlation_id": run_id + "-" + "b" * 32,
                  "user_id": "secret", "authorization": "Bearer secret", "exc": "secret",
                  "idempotency_key": "secret", "path": "/wallets", "status": 200,
                  "method": "POST", "ts": "2026-09-09T12:00:00.123Z"}
        exported = sanitize("app | " + json.dumps(record), run_id)
        self.assertNotIn("secret", json.dumps(exported))
        self.assertEqual(exported["status"], 200)
        self.assertIsNone(sanitize(json.dumps(record), "different-run"))
        self.assertIsNone(sanitize("not-json", run_id))


if __name__ == "__main__":
    unittest.main()