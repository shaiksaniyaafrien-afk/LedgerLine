import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Text,
)
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class LedgerEntryType(str, enum.Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    REFUSED = "REFUSED"


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, index=True)
    entry_type = Column(SQLEnum(LedgerEntryType), nullable=False)
    amount = Column(Numeric(18, 4), nullable=False)
    running_balance = Column(Numeric(18, 4), nullable=False)
    refusal_reason = Column(String(255), nullable=True)
    initiated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Cryptographic tamper-evident hash chaining
    prev_hash = Column(String(64), nullable=False, default="GENESIS")
    entry_hash = Column(String(64), nullable=False)
    
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    account = relationship("Account")
    transaction = relationship("Transaction")
    initiated_by = relationship("User")

    @staticmethod
    def calculate_entry_hash(
        prev_hash: str,
        account_id: int,
        transaction_id: int,
        entry_type: str,
        amount: Decimal,
        running_balance: Decimal,
        created_at_iso: str,
    ) -> str:
        payload = f"{prev_hash}|{account_id}|{transaction_id}|{entry_type}|{amount:.4f}|{running_balance:.4f}|{created_at_iso}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

