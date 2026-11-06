from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field

from app.models.transaction import TransactionType, TransactionStatus
from app.models.ledger import LedgerEntryType


class DepositRequest(BaseModel):
    account_id: int
    amount: Decimal = Field(..., gt=Decimal("0.0000"), description="Amount must be positive")
    description: Optional[str] = "Deposit funds"
    idempotency_key: Optional[str] = None


class WithdrawRequest(BaseModel):
    account_id: int
    amount: Decimal = Field(..., gt=Decimal("0.0000"), description="Amount must be positive")
    description: Optional[str] = "Withdraw funds"
    idempotency_key: Optional[str] = None


class TransferRequest(BaseModel):
    source_account_id: int
    destination_account_number: str
    amount: Decimal = Field(..., gt=Decimal("0.0000"), description="Amount must be positive")
    description: Optional[str] = "Transfer funds"
    idempotency_key: Optional[str] = None


class TransactionResponse(BaseModel):
    id: int
    reference: str
    idempotency_key: Optional[str] = None
    transaction_type: TransactionType
    source_account_id: Optional[int] = None
    destination_account_id: Optional[int] = None
    amount: Decimal
    currency: str
    status: TransactionStatus
    refusal_reason: Optional[str] = None
    initiated_by_user_id: int
    description: Optional[str] = None
    created_at: datetime
    is_duplicate: bool = False

    class Config:
        from_attributes = True


class StatementEntryResponse(BaseModel):
    entry_id: int
    transaction_id: int
    transaction_reference: str
    transaction_type: str
    entry_type: LedgerEntryType
    amount: Decimal
    running_balance: Decimal
    refusal_reason: Optional[str] = None
    initiated_by_name: str
    initiated_by_user_id: int
    entry_hash: str
    prev_hash: str
    created_at: datetime

    class Config:
        from_attributes = True


class AccountStatementResponse(BaseModel):
    account_id: int
    account_number: str
    current_balance: Decimal
    currency: str
    owner_name: str
    statement_entries: List[StatementEntryResponse]

