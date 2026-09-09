import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from scripts import burst


class BurstEvidenceTests(unittest.TestCase):
    def test_failed_metrics_preserve_evidence_and_failure(self):
        error = urllib.error.HTTPError("https://example.test/metrics", 502, "Bad Gateway", {}, None)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(burst.urllib.request, "urlopen", side_effect=error):
                with patch.object(burst, "FAILS", []), patch.object(burst, "PASSES", []):
                    burst.write_evidence(directory, 1.0, "# before\n", "tested-revision")
            evidence = Path(directory)
            summary = json.loads((evidence / "summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["failed"])
            self.assertEqual(summary["revision"], "tested-revision")
            self.assertTrue((evidence / "requests.jsonl").exists())
            self.assertEqual((evidence / "metrics-after.txt").read_text(encoding="utf-8"),
                             "# Metrics unavailable: HTTP 502\n")