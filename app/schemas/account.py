from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from typing import Optional
from app.models.account import AccountType, AccountStatus


class AccountCreateRequest(BaseModel):
    account_number: Optional[str] = None
    initial_deposit: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    currency: str = Field(default="INR", max_length=10)
    user_id: Optional[int] = None  # Admin can create accounts for other users


class AccountResponse(BaseModel):
    id: int
    account_number: str
    user_id: Optional[int]
    account_type: AccountType
    balance: Decimal
    currency: str
    status: AccountStatus
    created_at: datetime

    class Config:
        from_attributes = True


class AccountBalanceResponse(BaseModel):
    account_id: int
    account_number: str
    balance: Decimal
    currency: str
    status: AccountStatus

