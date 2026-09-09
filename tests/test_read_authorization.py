import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app import store


class ReadAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrelated_callers_cannot_read_wallets_or_transfers(self):
        for operation, row in ((store.get_wallet, {"user_id": "owner"}),
                               (store.get_transfer, {"permitted": False})):
            connection = AsyncMock()
            result = MagicMock()
            result.mappings.return_value.first.return_value = row
            connection.execute.return_value = result
            with patch("app.store.engine") as engine:
                engine.connect.return_value.__aenter__.return_value = connection
                with self.assertRaises(store.ApiError) as caught:
                    await operation("unrelated-user", uuid.uuid4())
                self.assertEqual(caught.exception.status, 403)


if __name__ == "__main__":
    unittest.main()