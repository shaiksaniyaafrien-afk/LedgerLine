import json
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.account import Account, AccountType, AccountStatus
from app.models.transaction import Transaction, TransactionType, TransactionStatus
from app.models.ledger import LedgerEntryType
from app.schemas.transaction import (
    DepositRequest,
    WithdrawRequest,
    TransferRequest,
    TransactionResponse,
)
from app.services.account_service import AccountService
from app.services.transaction_service import TransactionService
from app.services.idempotency_service import IdempotencyService
from app.services.ledger_service import LedgerService
from app.services.audit_service import AuditService

router = APIRouter(prefix="/api/transactions", tags=["Transactions"])


@router.post("/deposit", response_model=TransactionResponse)
def deposit(
    request: DepositRequest,
    req: Request,
    response: Response,
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ip = req.client.host if req.client else None
    idem_key = idempotency_key_header or request.idempotency_key

    # Auditors cannot move money
    if current_user.role == UserRole.AUDITOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditors have read-only privileges and cannot perform deposits.",
        )

    # Check account exists
    account = AccountService.get_account_by_id(db, request.account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Authorization check
    if current_user.role != UserRole.ADMIN and account.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to deposit into another user's account directly.",
        )

    # Idempotency check
    if idem_key:
        endpoint = "/api/transactions/deposit"
        payload = request.model_dump(mode="json")
        record, is_completed = IdempotencyService.check_or_create(
            db=db,
            user_id=current_user.id,
            key=idem_key,
            endpoint=endpoint,
            payload=payload,
        )
        if is_completed:
            response.headers["Idempotent-Replay"] = "true"
            cached_data = json.loads(record.response_body)
            cached_data["is_duplicate"] = True
            return cached_data

    # Execute deposit
    txn = TransactionService.execute_deposit(
        db=db,
        account_id=request.account_id,
        amount=request.amount,
        initiated_by_user_id=current_user.id,
        description=request.description,
        idempotency_key=idem_key,
        ip_address=ip,
    )

    result = TransactionResponse.model_validate(txn).model_dump(mode="json")
    if idem_key:
        IdempotencyService.finalize(
            db=db,
            key=idem_key,
            user_id=current_user.id,
            response_code=200,
            response_data=result,
        )

    return result


@router.post("/withdraw", response_model=TransactionResponse)
def withdraw(
    request: WithdrawRequest,
    req: Request,
    response: Response,
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ip = req.client.host if req.client else None
    idem_key = idempotency_key_header or request.idempotency_key

    # Auditors cannot move money
    if current_user.role == UserRole.AUDITOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditors have read-only privileges and cannot perform withdrawals.",
        )

    # Check account exists
    account = AccountService.get_account_by_id(db, request.account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Authorization: only account owner or admin can withdraw
    if current_user.role != UserRole.ADMIN and account.user_id != current_user.id:
        # Record refused attempt on the target account
        ref_id = TransactionService.generate_reference("WTH-REF")
        refused_txn = Transaction(
            reference=ref_id,
            idempotency_key=idem_key,
            transaction_type=TransactionType.WITHDRAWAL,
            source_account_id=account.id,
            amount=request.amount,
            currency=account.currency,
            status=TransactionStatus.REFUSED,
            refusal_reason="UNAUTHORIZED_ACCOUNT_ACCESS",
            initiated_by_user_id=current_user.id,
            description="Unauthorized withdrawal attempt",
        )
        db.add(refused_txn)
        db.flush()

        LedgerService.create_ledger_entry(
            db=db,
            account_id=account.id,
            transaction_id=refused_txn.id,
            entry_type=LedgerEntryType.REFUSED,
            amount=request.amount,
            running_balance=account.balance,
            initiated_by_user_id=current_user.id,
            refusal_reason="UNAUTHORIZED_ACCOUNT_ACCESS",
        )
        AuditService.log_event(
            db=db,
            action="UNAUTHORIZED_WITHDRAWAL_REFUSED",
            user_id=current_user.id,
            entity_type="ACCOUNT",
            entity_id=str(account.id),
            ip_address=ip,
            details={"attempted_amount": str(request.amount)},
        )
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot withdraw from an account you do not own.",
        )

    # Idempotency check
    if idem_key:
        endpoint = "/api/transactions/withdraw"
        payload = request.model_dump(mode="json")
        record, is_completed = IdempotencyService.check_or_create(
            db=db,
            user_id=current_user.id,
            key=idem_key,
            endpoint=endpoint,
            payload=payload,
        )
        if is_completed:
            response.headers["Idempotent-Replay"] = "true"
            cached_data = json.loads(record.response_body)
            cached_data["is_duplicate"] = True
            return cached_data

    # Execute withdrawal
    txn = TransactionService.execute_withdrawal(
        db=db,
        account_id=request.account_id,
        amount=request.amount,
        initiated_by_user_id=current_user.id,
        description=request.description,
        idempotency_key=idem_key,
        ip_address=ip,
    )

    result = TransactionResponse.model_validate(txn).model_dump(mode="json")
    if idem_key:
        IdempotencyService.finalize(
            db=db,
            key=idem_key,
            user_id=current_user.id,
            response_code=200,
            response_data=result,
        )

    return result


@router.post("/transfer", response_model=TransactionResponse)
def transfer(
    request: TransferRequest,
    req: Request,
    response: Response,
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ip = req.client.host if req.client else None
    idem_key = idempotency_key_header or request.idempotency_key

    # Auditors cannot move money
    if current_user.role == UserRole.AUDITOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditors have read-only privileges and cannot perform transfers.",
        )

    # Source account validation
    source_acc = AccountService.get_account_by_id(db, request.source_account_id)
    if not source_acc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source account not found",
        )

    # Authorization: only source account owner or admin can transfer out
    if current_user.role != UserRole.ADMIN and source_acc.user_id != current_user.id:
        ref_id = TransactionService.generate_reference("TRF-REF")
        refused_txn = Transaction(
            reference=ref_id,
            idempotency_key=idem_key,
            transaction_type=TransactionType.TRANSFER,
            source_account_id=source_acc.id,
            amount=request.amount,
            currency=source_acc.currency,
            status=TransactionStatus.REFUSED,
            refusal_reason="UNAUTHORIZED_ACCOUNT_ACCESS",
            initiated_by_user_id=current_user.id,
            description=f"Unauthorized transfer attempt to {request.destination_account_number}",
        )
        db.add(refused_txn)
        db.flush()

        LedgerService.create_ledger_entry(
            db=db,
            account_id=source_acc.id,
            transaction_id=refused_txn.id,
            entry_type=LedgerEntryType.REFUSED,
            amount=request.amount,
            running_balance=source_acc.balance,
            initiated_by_user_id=current_user.id,
            refusal_reason="UNAUTHORIZED_ACCOUNT_ACCESS",
        )
        AuditService.log_event(
            db=db,
            action="UNAUTHORIZED_TRANSFER_REFUSED",
            user_id=current_user.id,
            entity_type="ACCOUNT",
            entity_id=str(source_acc.id),
            ip_address=ip,
            details={"attempted_amount": str(request.amount)},
        )
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot transfer funds out of an account you do not own.",
        )

    # Idempotency check
    if idem_key:
        endpoint = "/api/transactions/transfer"
        payload = request.model_dump(mode="json")
        record, is_completed = IdempotencyService.check_or_create(
            db=db,
            user_id=current_user.id,
            key=idem_key,
            endpoint=endpoint,
            payload=payload,
        )
        if is_completed:
            response.headers["Idempotent-Replay"] = "true"
            cached_data = json.loads(record.response_body)
            cached_data["is_duplicate"] = True
            return cached_data

    # Execute transfer
    txn = TransactionService.execute_transfer(
        db=db,
        source_account_id=request.source_account_id,
        destination_account_number=request.destination_account_number,
        amount=request.amount,
        initiated_by_user_id=current_user.id,
        description=request.description,
        idempotency_key=idem_key,
        ip_address=ip,
    )

    result = TransactionResponse.model_validate(txn).model_dump(mode="json")
    if idem_key:
        IdempotencyService.finalize(
            db=db,
            key=idem_key,
            user_id=current_user.id,
            response_code=200,
            response_data=result,
        )

    return result

