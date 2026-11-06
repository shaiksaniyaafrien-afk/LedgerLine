from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    verify_account_access_for_reading,
)
from app.models.user import User, UserRole
from app.models.account import Account, AccountType
from app.schemas.account import AccountCreateRequest, AccountResponse
from app.schemas.transaction import AccountStatementResponse
from app.services.account_service import AccountService

router = APIRouter(prefix="/api/accounts", tags=["Accounts"])


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    request: AccountCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == UserRole.AUDITOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Auditors have read-only privileges and cannot create accounts.",
        )

    # Determine assigned user_id
    assigned_user_id = current_user.id
    if current_user.role == UserRole.ADMIN and request.user_id:
        assigned_user_id = request.user_id

    account = AccountService.create_account(
        db=db,
        user_id=assigned_user_id,
        account_number=request.account_number,
        initial_deposit=request.initial_deposit,
        currency=request.currency,
    )
    return account


@router.get("", response_model=List[AccountResponse])
def list_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Admin and Auditor see all customer accounts; Account Holder sees only their own
    if current_user.role in [UserRole.ADMIN, UserRole.AUDITOR]:
        return AccountService.get_all_accounts(db)
    return AccountService.get_user_accounts(db, current_user.id)


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = AccountService.get_account_by_id(db, account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    if not verify_account_access_for_reading(current_user, account):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot view this account.",
        )

    return account


@router.get("/{account_id}/statement", response_model=AccountStatementResponse)
def get_account_statement(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = AccountService.get_account_by_id(db, account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    if not verify_account_access_for_reading(current_user, account):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot view this statement.",
        )

    return AccountService.get_account_statement(db, account_id)
