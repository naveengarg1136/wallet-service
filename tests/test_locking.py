import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas import MAX_PAISE
from app.store import ApiError, _lock_wallets, _move_money


class WalletLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_directions_request_ordered_fk_compatible_locks(self):
        low_id = uuid.UUID(int=1)
        high_id = uuid.UUID(int=2)
        for first_id, second_id in ((low_id, high_id), (high_id, low_id)):
            with self.subTest(first=first_id):
                connection = MagicMock()
                connection.execute = AsyncMock()
                connection.execute.return_value = MagicMock()
                connection.execute.return_value.mappings.return_value.all.return_value = []
                await _lock_wallets(connection, first_id, second_id)
                statement, parameters = connection.execute.call_args.args
                self.assertIn("ORDER BY id FOR NO KEY UPDATE", str(statement))
                self.assertEqual({parameters["first"], parameters["second"]}, {low_id, high_id})

    async def test_recipient_overflow_and_insufficient_funds_never_update_balances(self):
        source, destination = uuid.uuid4(), uuid.uuid4()
        connection = AsyncMock()
        with patch("app.store._lock_wallets", new_callable=AsyncMock) as lock:
            lock.return_value = [{"id": source, "balance_paise": 10},
                                 {"id": destination, "balance_paise": MAX_PAISE}]
            with self.assertRaises(ApiError) as caught:
                await _move_money(connection, source, destination, 1)
            self.assertEqual(caught.exception.code, "balance_limit_exceeded")
            self.assertFalse(await _move_money(connection, source, destination, 11))
            connection.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()