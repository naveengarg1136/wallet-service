import unittest
import uuid

from pydantic import ValidationError

from app.schemas import DepositIn, MAX_PAISE, TransferIn


class MoneySchemaTests(unittest.TestCase):
    def test_only_positive_bigint_json_integers_are_accepted(self):
        for model in (DepositIn, TransferIn):
            body = {"from": str(uuid.uuid4()), "to": str(uuid.uuid4()), "idempotency_key": "test"}
            for amount in (True, False, 1.0, 1.5, "1", None, 0, -1, MAX_PAISE + 1):
                with self.subTest(model=model.__name__, amount=repr(amount)):
                    with self.assertRaises(ValidationError):
                        model.model_validate({**body, "amount_paise": amount})
            for amount in (1, MAX_PAISE):
                self.assertEqual(model.model_validate({**body, "amount_paise": amount}).amount_paise, amount)


if __name__ == "__main__":
    unittest.main()