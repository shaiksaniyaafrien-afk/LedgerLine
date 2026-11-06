import random
import string
from decimal import Decimal
from typing import Optional, List
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.account import Account, AccountType, AccountStatus
from app.models.ledger import LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import StatementEntryResponse, AccountStatementResponse


class AccountService:
    @staticmethod
    def generate_account_number() -> str:
        suffix = "".join(random.choices(string.digits, k=8))
        return f"ACC-{suffix}"

    @staticmethod
    def get_or_create_system_clearing_account(db: Session) -> Account:
        clearing_acc = (
            db.query(Account)
            .filter(Account.account_type == AccountType.SYSTEM_CLEARING)
            .first()
        )
        if not clearing_acc:
            clearing_acc = Account(
                account_number="SYS-CLEARING-RESERVE",
                account_type=AccountType.SYSTEM_CLEARING,
                balance=Decimal("1000000000.0000"),  # Reserve clearing balance
                currency="INR",
                status=AccountStatus.ACTIVE,
            )
            db.add(clearing_acc)
            db.commit()
            db.refresh(clearing_acc)
        return clearing_acc

    @staticmethod
    def create_account(
        db: Session,
        user_id: int,
        account_number: Optional[str] = None,
        initial_deposit: Decimal = Decimal("0.0000"),
        currency: str = "INR",
    ) -> Account:
        if not account_number:
            account_number = AccountService.generate_account_number()

        # Check uniqueness
        existing = db.query(Account).filter(Account.account_number == account_number).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Account number '{account_number}' already exists.",
            )

        account = Account(
            account_number=account_number,
            user_id=user_id,
            account_type=AccountType.CUSTOMER,
            balance=Decimal("0.0000"),
            currency=currency,
            status=AccountStatus.ACTIVE,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        # If initial deposit specified, execute deposit via transaction service
        if initial_deposit > Decimal("0.0000"):
            from app.services.transaction_service import TransactionService
            TransactionService.execute_deposit(
                db=db,
                account_id=account.id,
                amount=initial_deposit,
                initiated_by_user_id=user_id,
                description="Initial Account Opening Deposit",
                idempotency_key=f"OPEN-{account.account_number}",
            )
            db.refresh(account)

        return account

    @staticmethod
    def get_account_by_id(db: Session, account_id: int) -> Optional[Account]:
        return db.query(Account).filter(Account.id == account_id).first()

    @staticmethod
    def get_account_by_number(db: Session, account_number: str) -> Optional[Account]:
        return db.query(Account).filter(Account.account_number == account_number).first()

    @staticmethod
    def get_user_accounts(db: Session, user_id: int) -> List[Account]:
        return (
            db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.account_type == AccountType.CUSTOMER,
            )
            .order_by(Account.id.asc())
            .all()
        )

    @staticmethod
    def get_all_accounts(db: Session) -> List[Account]:
        return db.query(Account).order_by(Account.id.asc()).all()

    @staticmethod
    def get_account_statement(
        db: Session,
        account_id: int,
    ) -> AccountStatementResponse:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        owner_name = account.user.full_name if account.user else "System Reserve"

        # Fetch all ledger entries including REFUSED attempts
        entries = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.account_id == account_id)
            .order_by(LedgerEntry.id.asc())
            .all()
        )

        statement_entries: List[StatementEntryResponse] = []
        for e in entries:
            txn = db.query(Transaction).filter(Transaction.id == e.transaction_id).first()
            user = db.query(User).filter(User.id == e.initiated_by_user_id).first()
            user_name = user.full_name if user else "Unknown"
            txn_ref = txn.reference if txn else "N/A"
            txn_type = txn.transaction_type.value if txn else "N/A"

            statement_entries.append(
                StatementEntryResponse(
                    entry_id=e.id,
                    transaction_id=e.transaction_id,
                    transaction_reference=txn_ref,
                    transaction_type=txn_type,
                    entry_type=e.entry_type,
                    amount=Decimal(str(e.amount)),
                    running_balance=Decimal(str(e.running_balance)),
                    refusal_reason=e.refusal_reason,
                    initiated_by_name=user_name,
                    initiated_by_user_id=e.initiated_by_user_id,
                    entry_hash=e.entry_hash,
                    prev_hash=e.prev_hash,
                    created_at=e.created_at,
                )
            )

        return AccountStatementResponse(
            account_id=account.id,
            account_number=account.account_number,
            current_balance=Decimal(str(account.balance)),
            currency=account.currency,
            owner_name=owner_name,
            statement_entries=statement_entries,
        )

