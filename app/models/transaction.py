from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Enum as SQLEnum,
    Text,
)
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class TransactionType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSFER = "TRANSFER"


class TransactionStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(100), unique=True, nullable=False, index=True)
    idempotency_key = Column(String(255), nullable=True, index=True)
    transaction_type = Column(SQLEnum(TransactionType), nullable=False)
    source_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    destination_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    amount = Column(Numeric(18, 4), nullable=False)
    currency = Column(String(10), nullable=False, default="INR")
    status = Column(SQLEnum(TransactionStatus), nullable=False)
    refusal_reason = Column(String(255), nullable=True)
    initiated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    source_account = relationship("Account", foreign_keys=[source_account_id])
    destination_account = relationship("Account", foreign_keys=[destination_account_id])
    initiated_by = relationship("User", foreign_keys=[initiated_by_user_id])

    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_transaction_amount_positive"),
    )
