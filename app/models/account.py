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
)
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class AccountType(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    SYSTEM_CLEARING = "SYSTEM_CLEARING"


class AccountStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_number = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    account_type = Column(
        SQLEnum(AccountType),
        nullable=False,
        default=AccountType.CUSTOMER,
    )
    # Currency balance with 4 decimal places for exact banking math
    balance = Column(Numeric(18, 4), nullable=False, default=Decimal("0.0000"))
    currency = Column(String(10), nullable=False, default="INR")
    status = Column(
        SQLEnum(AccountStatus),
        nullable=False,
        default=AccountStatus.ACTIVE,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = relationship("User", backref="accounts")

    __table_args__ = (
        CheckConstraint(
            "balance >= 0",
            name="chk_account_balance_non_negative",
        ),
    )

