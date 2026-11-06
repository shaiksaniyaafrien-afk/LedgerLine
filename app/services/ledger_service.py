from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.ledger import LedgerEntry, LedgerEntryType
from app.models.account import Account, AccountType
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.schemas.audit import (
    SystemReconciliationResponse,
    TamperProofReportResponse,
    TamperVerificationEntry,
)


class LedgerService:
    @staticmethod
    def create_ledger_entry(
        db: Session,
        account_id: int,
        transaction_id: int,
        entry_type: LedgerEntryType,
        amount: Decimal,
        running_balance: Decimal,
        initiated_by_user_id: int,
        refusal_reason: Optional[str] = None,
    ) -> LedgerEntry:
        # Fetch the last ledger entry for this account to maintain cryptographic chain
        last_entry = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.account_id == account_id)
            .order_by(LedgerEntry.id.desc())
            .first()
        )

        prev_hash = last_entry.entry_hash if last_entry else "GENESIS"
        now = datetime.now(timezone.utc)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        entry_hash = LedgerEntry.calculate_entry_hash(
            prev_hash=prev_hash,
            account_id=account_id,
            transaction_id=transaction_id,
            entry_type=entry_type.value,
            amount=amount,
            running_balance=running_balance,
            created_at_iso=now_str,
        )

        entry = LedgerEntry(
            account_id=account_id,
            transaction_id=transaction_id,
            entry_type=entry_type,
            amount=amount,
            running_balance=running_balance,
            refusal_reason=refusal_reason,
            initiated_by_user_id=initiated_by_user_id,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
            created_at=now,
        )
        db.add(entry)
        return entry

    @staticmethod
    def verify_account_ledger_chain(
        db: Session,
        account_id: int,
    ) -> Tuple[bool, int, Optional[int], Optional[str]]:
        """
        Validates cryptographic hash chain for a specific account.
        Returns: (is_valid, total_checked, corrupted_entry_id, error_message)
        """
        entries = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.account_id == account_id)
            .order_by(LedgerEntry.id.asc())
            .all()
        )

        if not entries:
            return True, 0, None, None

        expected_prev_hash = "GENESIS"
        for entry in entries:
            # Check prev_hash continuity
            if entry.prev_hash != expected_prev_hash:
                return (
                    False,
                    len(entries),
                    entry.id,
                    f"Chain broken at entry #{entry.id}: expected prev_hash '{expected_prev_hash[:10]}...' but found '{entry.prev_hash[:10]}...'",
                )

            # Recompute and verify entry_hash
            computed_hash = LedgerEntry.calculate_entry_hash(
                prev_hash=entry.prev_hash,
                account_id=entry.account_id,
                transaction_id=entry.transaction_id,
                entry_type=entry.entry_type.value,
                amount=Decimal(str(entry.amount)),
                running_balance=Decimal(str(entry.running_balance)),
                created_at_iso=entry.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

            if computed_hash != entry.entry_hash:
                return (
                    False,
                    len(entries),
                    entry.id,
                    f"Cryptographic tamper detected at entry #{entry.id}: computed hash '{computed_hash[:10]}...' != stored hash '{entry.entry_hash[:10]}...'",
                )

            expected_prev_hash = entry.entry_hash

        return True, len(entries), None, None

    @staticmethod
    def verify_system_tamper_proof(db: Session) -> TamperProofReportResponse:
        """
        Auditor tool: mathematically validates hash chains across all accounts.
        """
        accounts = db.query(Account).order_by(Account.id.asc()).all()
        all_valid = True
        total_entries = 0
        details: List[TamperVerificationEntry] = []

        for acc in accounts:
            valid, count, err_id, msg = LedgerService.verify_account_ledger_chain(db, acc.id)
            total_entries += count
            if not valid:
                all_valid = False
            details.append(
                TamperVerificationEntry(
                    account_id=acc.id,
                    account_number=acc.account_number,
                    is_valid=valid,
                    total_entries_verified=count,
                    corrupted_entry_id=err_id,
                    error_message=msg,
                )
            )

        return TamperProofReportResponse(
            all_chains_valid=all_valid,
            accounts_checked=len(accounts),
            total_entries_checked=total_entries,
            details=details,
            checked_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def get_system_reconciliation(db: Session) -> SystemReconciliationResponse:
        """
        Auditor & Admin tool: verifies global conservation of money invariant.
        Invariant:
          Total Customer Balances == Total External Deposits - Total External Withdrawals
          Total Debits == Total Credits in double-entry ledger postings
          Discrepancy == 0.0000
        """
        # Sum of customer balances
        customer_balance_sum = (
            db.query(func.coalesce(func.sum(Account.balance), Decimal("0.0000")))
            .filter(Account.account_type == AccountType.CUSTOMER)
            .scalar()
        ) or Decimal("0.0000")

        # Sum of completed external deposits
        total_deposits = (
            db.query(func.coalesce(func.sum(Transaction.amount), Decimal("0.0000")))
            .filter(
                Transaction.transaction_type == TransactionType.DEPOSIT,
                Transaction.status == TransactionStatus.COMPLETED,
            )
            .scalar()
        ) or Decimal("0.0000")

        # Sum of completed external withdrawals
        total_withdrawals = (
            db.query(func.coalesce(func.sum(Transaction.amount), Decimal("0.0000")))
            .filter(
                Transaction.transaction_type == TransactionType.WITHDRAWAL,
                Transaction.status == TransactionStatus.COMPLETED,
            )
            .scalar()
        ) or Decimal("0.0000")

        # Sum of completed internal transfers
        transfers_volume = (
            db.query(func.coalesce(func.sum(Transaction.amount), Decimal("0.0000")))
            .filter(
                Transaction.transaction_type == TransactionType.TRANSFER,
                Transaction.status == TransactionStatus.COMPLETED,
            )
            .scalar()
        ) or Decimal("0.0000")

        # Double-entry ledger sums (Credits vs Debits)
        total_credits = (
            db.query(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.0000")))
            .filter(LedgerEntry.entry_type == LedgerEntryType.CREDIT)
            .scalar()
        ) or Decimal("0.0000")

        total_debits = (
            db.query(func.coalesce(func.sum(LedgerEntry.amount), Decimal("0.0000")))
            .filter(LedgerEntry.entry_type == LedgerEntryType.DEBIT)
            .scalar()
        ) or Decimal("0.0000")

        expected_balance = total_deposits - total_withdrawals
        discrepancy = customer_balance_sum - expected_balance

        # Counts
        total_accounts = db.query(Account).count()
        total_ledger_entries = db.query(LedgerEntry).count()
        total_refused_attempts = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.entry_type == LedgerEntryType.REFUSED)
            .count()
        )

        is_balanced = (
            discrepancy == Decimal("0.0000")
            and customer_balance_sum >= Decimal("0.0000")
        )

        return SystemReconciliationResponse(
            is_balanced=is_balanced,
            total_customer_balances=Decimal(str(customer_balance_sum)),
            total_external_deposits=Decimal(str(total_deposits)),
            total_external_withdrawals=Decimal(str(total_withdrawals)),
            expected_customer_balances=Decimal(str(expected_balance)),
            discrepancy=Decimal(str(discrepancy)),
            total_internal_transfers_volume=Decimal(str(transfers_volume)),
            total_credits=Decimal(str(total_credits)),
            total_debits=Decimal(str(total_debits)),
            ledger_double_entry_balanced=(total_credits == total_debits),
            total_accounts=total_accounts,
            total_ledger_entries=total_ledger_entries,
            total_refused_attempts=total_refused_attempts,
            checked_at=datetime.now(timezone.utc),
        )
