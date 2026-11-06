import uuid
from decimal import Decimal
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, update
from fastapi import HTTPException, status

from app.models.account import Account, AccountType, AccountStatus
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.ledger import LedgerEntry, LedgerEntryType
from app.services.ledger_service import LedgerService
from app.services.audit_service import AuditService
from app.services.account_service import AccountService


class TransactionService:
    @staticmethod
    def generate_reference(prefix: str = "TXN") -> str:
        unique_suffix = uuid.uuid4().hex[:12].upper()
        return f"{prefix}-{unique_suffix}"

    @staticmethod
    def execute_deposit(
        db: Session,
        account_id: int,
        amount: Decimal,
        initiated_by_user_id: int,
        description: Optional[str] = "External Deposit",
        idempotency_key: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Transaction:
        amount = Decimal(str(amount))
        if amount <= Decimal("0.0000"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Deposit amount must be strictly positive",
            )

        clearing_acc = AccountService.get_or_create_system_clearing_account(db)

        # Order row locking to prevent deadlocks
        first_id, second_id = sorted([account_id, clearing_acc.id])
        acc1 = db.query(Account).filter(Account.id == first_id).with_for_update().first()
        acc2 = db.query(Account).filter(Account.id == second_id).with_for_update().first()

        account = acc1 if acc1.id == account_id else acc2
        system_clearing = acc1 if acc1.id == clearing_acc.id else acc2

        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        if account.status != AccountStatus.ACTIVE:
            # Log refused transaction
            ref_id = TransactionService.generate_reference("DEP-REF")
            refused_txn = Transaction(
                reference=ref_id,
                idempotency_key=idempotency_key,
                transaction_type=TransactionType.DEPOSIT,
                destination_account_id=account.id,
                amount=amount,
                currency=account.currency,
                status=TransactionStatus.REFUSED,
                refusal_reason="ACCOUNT_NOT_ACTIVE",
                initiated_by_user_id=initiated_by_user_id,
                description=description,
            )
            db.add(refused_txn)
            db.flush()

            LedgerService.create_ledger_entry(
                db=db,
                account_id=account.id,
                transaction_id=refused_txn.id,
                entry_type=LedgerEntryType.REFUSED,
                amount=amount,
                running_balance=account.balance,
                initiated_by_user_id=initiated_by_user_id,
                refusal_reason="ACCOUNT_NOT_ACTIVE",
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Deposit refused: Account status is {account.status.value}",
            )

        # Execute Deposit: Credit customer account, Debit system clearing
        account.balance = Decimal(str(account.balance)) + amount
        system_clearing.balance = Decimal(str(system_clearing.balance)) - amount

        reference = TransactionService.generate_reference("DEP")
        txn = Transaction(
            reference=reference,
            idempotency_key=idempotency_key,
            transaction_type=TransactionType.DEPOSIT,
            source_account_id=system_clearing.id,
            destination_account_id=account.id,
            amount=amount,
            currency=account.currency,
            status=TransactionStatus.COMPLETED,
            initiated_by_user_id=initiated_by_user_id,
            description=description,
        )
        db.add(txn)
        db.flush()

        # Double-entry ledger entries
        # 1. Credit customer account
        LedgerService.create_ledger_entry(
            db=db,
            account_id=account.id,
            transaction_id=txn.id,
            entry_type=LedgerEntryType.CREDIT,
            amount=amount,
            running_balance=account.balance,
            initiated_by_user_id=initiated_by_user_id,
        )

        # 2. Debit system clearing account
        LedgerService.create_ledger_entry(
            db=db,
            account_id=system_clearing.id,
            transaction_id=txn.id,
            entry_type=LedgerEntryType.DEBIT,
            amount=amount,
            running_balance=system_clearing.balance,
            initiated_by_user_id=initiated_by_user_id,
        )

        AuditService.log_event(
            db=db,
            action="DEPOSIT_COMPLETED",
            user_id=initiated_by_user_id,
            entity_type="TRANSACTION",
            entity_id=txn.reference,
            ip_address=ip_address,
            details={"amount": str(amount), "account_id": account.id},
        )

        db.commit()
        db.refresh(txn)
        return txn

    @staticmethod
    def execute_withdrawal(
        db: Session,
        account_id: int,
        amount: Decimal,
        initiated_by_user_id: int,
        description: Optional[str] = "External Withdrawal",
        idempotency_key: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Transaction:
        amount = Decimal(str(amount))
        if amount <= Decimal("0.0000"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Withdrawal amount must be strictly positive",
            )

        clearing_acc = AccountService.get_or_create_system_clearing_account(db)

        # Lock rows in deterministic ascending ID order
        first_id, second_id = sorted([account_id, clearing_acc.id])
        acc1 = db.query(Account).filter(Account.id == first_id).with_for_update().first()
        acc2 = db.query(Account).filter(Account.id == second_id).with_for_update().first()

        account = acc1 if acc1.id == account_id else acc2
        system_clearing = acc1 if acc1.id == clearing_acc.id else acc2

        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found",
            )

        if account.status != AccountStatus.ACTIVE:
            ref_id = TransactionService.generate_reference("WTH-REF")
            refused_txn = Transaction(
                reference=ref_id,
                idempotency_key=idempotency_key,
                transaction_type=TransactionType.WITHDRAWAL,
                source_account_id=account.id,
                amount=amount,
                currency=account.currency,
                status=TransactionStatus.REFUSED,
                refusal_reason="ACCOUNT_NOT_ACTIVE",
                initiated_by_user_id=initiated_by_user_id,
                description=description,
            )
            db.add(refused_txn)
            db.flush()

            LedgerService.create_ledger_entry(
                db=db,
                account_id=account.id,
                transaction_id=refused_txn.id,
                entry_type=LedgerEntryType.REFUSED,
                amount=amount,
                running_balance=account.balance,
                initiated_by_user_id=initiated_by_user_id,
                refusal_reason="ACCOUNT_NOT_ACTIVE",
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Withdrawal refused: Account status is {account.status.value}",
            )

        # Atomic balance reduction: guarantees no overdraft under concurrency
        update_stmt = (
            update(Account)
            .where(Account.id == account.id, Account.balance >= amount)
            .values(balance=Account.balance - amount)
        )
        update_res = db.execute(update_stmt)

        # Check balance constraint via atomic rowcount
        if update_res.rowcount == 0:
            ref_id = TransactionService.generate_reference("WTH-REF")
            refused_txn = Transaction(
                reference=ref_id,
                idempotency_key=idempotency_key,
                transaction_type=TransactionType.WITHDRAWAL,
                source_account_id=account.id,
                amount=amount,
                currency=account.currency,
                status=TransactionStatus.REFUSED,
                refusal_reason="INSUFFICIENT_FUNDS",
                initiated_by_user_id=initiated_by_user_id,
                description=description,
            )
            db.add(refused_txn)
            db.flush()

            LedgerService.create_ledger_entry(
                db=db,
                account_id=account.id,
                transaction_id=refused_txn.id,
                entry_type=LedgerEntryType.REFUSED,
                amount=amount,
                running_balance=account.balance,
                initiated_by_user_id=initiated_by_user_id,
                refusal_reason="INSUFFICIENT_FUNDS",
            )
            AuditService.log_event(
                db=db,
                action="WITHDRAWAL_REFUSED",
                user_id=initiated_by_user_id,
                entity_type="ACCOUNT",
                entity_id=str(account.id),
                ip_address=ip_address,
                details={
                    "reason": "INSUFFICIENT_FUNDS",
                    "attempted_amount": str(amount),
                    "balance": str(account.balance),
                },
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Withdrawal refused: Insufficient funds. Available balance: {account.balance}",
            )

        # Update clearing account
        db.execute(
            update(Account)
            .where(Account.id == system_clearing.id)
            .values(balance=Account.balance + amount)
        )
        db.refresh(account)
        db.refresh(system_clearing)

        reference = TransactionService.generate_reference("WTH")
        txn = Transaction(
            reference=reference,
            idempotency_key=idempotency_key,
            transaction_type=TransactionType.WITHDRAWAL,
            source_account_id=account.id,
            destination_account_id=system_clearing.id,
            amount=amount,
            currency=account.currency,
            status=TransactionStatus.COMPLETED,
            initiated_by_user_id=initiated_by_user_id,
            description=description,
        )
        db.add(txn)
        db.flush()

        # Double-entry ledger entries
        # 1. Debit customer account
        LedgerService.create_ledger_entry(
            db=db,
            account_id=account.id,
            transaction_id=txn.id,
            entry_type=LedgerEntryType.DEBIT,
            amount=amount,
            running_balance=account.balance,
            initiated_by_user_id=initiated_by_user_id,
        )

        # 2. Credit system clearing account
        LedgerService.create_ledger_entry(
            db=db,
            account_id=system_clearing.id,
            transaction_id=txn.id,
            entry_type=LedgerEntryType.CREDIT,
            amount=amount,
            running_balance=system_clearing.balance,
            initiated_by_user_id=initiated_by_user_id,
        )

        AuditService.log_event(
            db=db,
            action="WITHDRAWAL_COMPLETED",
            user_id=initiated_by_user_id,
            entity_type="TRANSACTION",
            entity_id=txn.reference,
            ip_address=ip_address,
            details={"amount": str(amount), "account_id": account.id},
        )

        db.commit()
        db.refresh(txn)
        return txn

    @staticmethod
    def execute_transfer(
        db: Session,
        source_account_id: int,
        destination_account_number: str,
        amount: Decimal,
        initiated_by_user_id: int,
        description: Optional[str] = "Account Transfer",
        idempotency_key: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Transaction:
        amount = Decimal(str(amount))
        if amount <= Decimal("0.0000"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transfer amount must be strictly positive",
            )

        # Resolve destination account
        dest_account_check = (
            db.query(Account)
            .filter(Account.account_number == destination_account_number)
            .first()
        )
        if not dest_account_check:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Destination account '{destination_account_number}' not found",
            )

        if source_account_id == dest_account_check.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot transfer money to the same account",
            )

        destination_account_id = dest_account_check.id

        # Deadlock prevention: Lock accounts in strictly ascending ID order
        first_id, second_id = sorted([source_account_id, destination_account_id])
        acc1 = db.query(Account).filter(Account.id == first_id).with_for_update().first()
        acc2 = db.query(Account).filter(Account.id == second_id).with_for_update().first()

        source_acc = acc1 if acc1.id == source_account_id else acc2
        dest_acc = acc1 if acc1.id == destination_account_id else acc2

        if not source_acc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source account not found",
            )

        # Validate accounts are active
        if source_acc.status != AccountStatus.ACTIVE or dest_acc.status != AccountStatus.ACTIVE:
            reason = "SOURCE_ACCOUNT_INACTIVE" if source_acc.status != AccountStatus.ACTIVE else "DESTINATION_ACCOUNT_INACTIVE"
            ref_id = TransactionService.generate_reference("TRF-REF")
            refused_txn = Transaction(
                reference=ref_id,
                idempotency_key=idempotency_key,
                transaction_type=TransactionType.TRANSFER,
                source_account_id=source_acc.id,
                destination_account_id=dest_acc.id,
                amount=amount,
                currency=source_acc.currency,
                status=TransactionStatus.REFUSED,
                refusal_reason=reason,
                initiated_by_user_id=initiated_by_user_id,
                description=description,
            )
            db.add(refused_txn)
            db.flush()

            LedgerService.create_ledger_entry(
                db=db,
                account_id=source_acc.id,
                transaction_id=refused_txn.id,
                entry_type=LedgerEntryType.REFUSED,
                amount=amount,
                running_balance=source_acc.balance,
                initiated_by_user_id=initiated_by_user_id,
                refusal_reason=reason,
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Transfer refused: {reason}",
            )

        # Atomic balance reduction: guarantees no overdraft under concurrent transfers
        transfer_deduct_stmt = (
            update(Account)
            .where(Account.id == source_acc.id, Account.balance >= amount)
            .values(balance=Account.balance - amount)
        )
        update_res = db.execute(transfer_deduct_stmt)

        # Check balance constraint via atomic rowcount
        if update_res.rowcount == 0:
            ref_id = TransactionService.generate_reference("TRF-REF")
            refused_txn = Transaction(
                reference=ref_id,
                idempotency_key=idempotency_key,
                transaction_type=TransactionType.TRANSFER,
                source_account_id=source_acc.id,
                destination_account_id=dest_acc.id,
                amount=amount,
                currency=source_acc.currency,
                status=TransactionStatus.REFUSED,
                refusal_reason="INSUFFICIENT_FUNDS",
                initiated_by_user_id=initiated_by_user_id,
                description=description,
            )
            db.add(refused_txn)
            db.flush()

            # Record refused entry in source account statement
            LedgerService.create_ledger_entry(
                db=db,
                account_id=source_acc.id,
                transaction_id=refused_txn.id,
                entry_type=LedgerEntryType.REFUSED,
                amount=amount,
                running_balance=source_acc.balance,
                initiated_by_user_id=initiated_by_user_id,
                refusal_reason="INSUFFICIENT_FUNDS",
            )
            AuditService.log_event(
                db=db,
                action="TRANSFER_REFUSED",
                user_id=initiated_by_user_id,
                entity_type="ACCOUNT",
                entity_id=str(source_acc.id),
                ip_address=ip_address,
                details={
                    "reason": "INSUFFICIENT_FUNDS",
                    "attempted_amount": str(amount),
                    "balance": str(source_acc.balance),
                    "destination": dest_acc.account_number,
                },
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Transfer refused: Insufficient funds. Available balance: {source_acc.balance}",
            )

        # Atomically credit destination
        db.execute(
            update(Account)
            .where(Account.id == dest_acc.id)
            .values(balance=Account.balance + amount)
        )
        db.refresh(source_acc)
        db.refresh(dest_acc)

        reference = TransactionService.generate_reference("TRF")
        txn = Transaction(
            reference=reference,
            idempotency_key=idempotency_key,
            transaction_type=TransactionType.TRANSFER,
            source_account_id=source_acc.id,
            destination_account_id=dest_acc.id,
            amount=amount,
            currency=source_acc.currency,
            status=TransactionStatus.COMPLETED,
            initiated_by_user_id=initiated_by_user_id,
            description=description,
        )
        db.add(txn)
        db.flush()

        # Double-entry ledger entries:
        # 1. Debit on source account
        LedgerService.create_ledger_entry(
            db=db,
            account_id=source_acc.id,
            transaction_id=txn.id,
            entry_type=LedgerEntryType.DEBIT,
            amount=amount,
            running_balance=source_acc.balance,
            initiated_by_user_id=initiated_by_user_id,
        )

        # 2. Credit on destination account
        LedgerService.create_ledger_entry(
            db=db,
            account_id=dest_acc.id,
            transaction_id=txn.id,
            entry_type=LedgerEntryType.CREDIT,
            amount=amount,
            running_balance=dest_acc.balance,
            initiated_by_user_id=initiated_by_user_id,
        )

        AuditService.log_event(
            db=db,
            action="TRANSFER_COMPLETED",
            user_id=initiated_by_user_id,
            entity_type="TRANSACTION",
            entity_id=txn.reference,
            ip_address=ip_address,
            details={
                "amount": str(amount),
                "source_account": source_acc.account_number,
                "destination_account": dest_acc.account_number,
            },
        )

        db.commit()
        db.refresh(txn)
        return txn
