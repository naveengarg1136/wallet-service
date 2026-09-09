import unittest

from sqlalchemy.engine import make_url

from app.config import _normalize_db_url, _requires_tls


class ConfigTests(unittest.TestCase):
    def test_encoded_credentials_survive_url_normalization(self):
        original = "postgres://user:p%40ss%26word@localhost/db?sslmode=require&channel_binding=require"
        normalized = make_url(_normalize_db_url(original))
        self.assertEqual(normalized.password, "p@ss&word")
        self.assertEqual(normalized.drivername, "postgresql+asyncpg")
        self.assertNotIn("sslmode", normalized.query)
        self.assertNotIn("channel_binding", normalized.query)

    def test_tls_requirement_is_not_discarded_with_libpq_parameters(self):
        base = "postgresql://user:password@localhost/db"
        for mode in ("require", "verify-ca", "verify-full", "prefer", "allow"):
            self.assertTrue(_requires_tls(base + "?sslmode=" + mode, ""))
        self.assertFalse(_requires_tls(base, ""))
        self.assertTrue(_requires_tls(base, "require"))


if __name__ == "__main__":
    unittest.main()