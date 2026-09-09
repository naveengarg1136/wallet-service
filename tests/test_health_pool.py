import asyncio
import os
import unittest
from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app import db
from app.main import healthz


class HealthPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_uses_reserved_pool_and_reports_database_failure(self):
        connection = MagicMock()
        connection.execute = AsyncMock()
        reserved = MagicMock()
        reserved.connect.return_value.__aenter__ = AsyncMock(return_value=connection)
        reserved.connect.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(db, "health_engine", reserved), patch.object(db, "engine") as busy:
            busy.connect.side_effect = PoolTimeoutError("request pool exhausted")
            self.assertEqual(await healthz(), {"status": "ok"})
            busy.connect.assert_not_called()
            connection.execute.side_effect = OSError("database unreachable")
            with self.assertRaises(HTTPException) as caught:
                await healthz()
            self.assertEqual(caught.exception.status_code, 503)

    @unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "requires disposable PostgreSQL")
    async def test_real_database_probe_survives_exhausted_request_pool(self):
        self.assertEqual(str(db.engine.url), os.environ["TEST_DATABASE_URL"])
        try:
            async with AsyncExitStack() as stack:
                for _ in range(15):
                    await stack.enter_async_context(db.engine.connect())
                self.assertEqual(db.engine.pool.checkedout(), 15)
                async with asyncio.timeout(0.1):
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(db.engine.connect(), timeout=0.05)
                self.assertEqual(await asyncio.wait_for(healthz(), timeout=3), {"status": "ok"})
        finally:
            await db.engine.dispose()
            await db.health_engine.dispose()