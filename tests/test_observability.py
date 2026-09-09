import json
import logging
import unittest
from types import SimpleNamespace

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.logging_conf import JsonFormatter, correlation_id
from app.main import observability


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def request(self, request_id="test-correlation"):
        return Request({"type": "http", "method": "GET", "path": "/test", "headers": [
            (b"x-request-id", request_id.encode())], "route": SimpleNamespace(path="/test")})

    async def test_errors_keep_correlation_and_do_not_log_exception_secrets(self):
        for error, status in ((RuntimeError("secret-value"), 500), (ConnectionError("secret-value"), 503)):
            async def fail(_):
                raise error

            with self.assertLogs("wallet", level="INFO") as logs:
                response = await observability(self.request(), fail)
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.headers["x-request-id"], "test-correlation")
            self.assertEqual(json.loads(response.body)["correlation_id"], "test-correlation")
            self.assertNotIn("secret-value", "".join(logs.output))
            self.assertEqual(correlation_id.get(), "-")
            self.assertEqual(logs.records[-1].fields["status"], status)

    async def test_invalid_request_id_is_replaced(self):
        async def success(_):
            return JSONResponse({"ok": True})

        response = await observability(self.request("bad id"), success)
        self.assertRegex(response.headers["x-request-id"], r"^[a-f0-9]{32}$")

    def test_timestamp_uses_utc_and_real_milliseconds(self):
        record = logging.LogRecord("wallet", logging.INFO, "", 0, "test", (), None)
        record.created = 0.125
        self.assertEqual(json.loads(JsonFormatter().format(record))["ts"], "1970-01-01T00:00:00.125Z")


if __name__ == "__main__":
    unittest.main()