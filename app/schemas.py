import uuid

from pydantic import BaseModel, ConfigDict, Field

MAX_PAISE = 2**63 - 1


class WalletOut(BaseModel):
    id: str
    user_id: str
    balance_paise: int


class TransferIn(BaseModel):
    # The exercise body uses `from`/`to`; both are Python-unfriendly / a keyword,
    # so we alias them and also accept the explicit field names.
    from_wallet: uuid.UUID = Field(alias="from")
    to_wallet: uuid.UUID = Field(alias="to")
    amount_paise: int = Field(strict=True, gt=0, le=MAX_PAISE)
    idempotency_key: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(populate_by_name=True)


class DepositIn(BaseModel):
    amount_paise: int = Field(strict=True, gt=0, le=MAX_PAISE)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ReverseIn(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)


class TransferOut(BaseModel):
    id: str
    idempotency_key: str
    from_wallet: str | None
    to_wallet: str | None
    amount_paise: int
    status: str
    kind: str
    reversal_of: str | None
    reversed_by: str | None
    decline_reason: str | None
    created_at: str | None
