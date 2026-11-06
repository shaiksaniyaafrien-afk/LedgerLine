from typing import List, Optional
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole
from app.models.account import Account

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    # Support both OAuth2PasswordBearer and direct Authorization header
    raw_token = token
    if not raw_token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(raw_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username: str = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account is deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_roles(allowed_roles: List[UserRole]):
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Required roles: {[r.value for r in allowed_roles]}",
            )
        return current_user
    return role_checker


# Specific role guards
require_admin = require_roles([UserRole.ADMIN])
require_auditor = require_roles([UserRole.ADMIN, UserRole.AUDITOR])
require_any_authenticated = require_roles([UserRole.ADMIN, UserRole.ACCOUNT_HOLDER, UserRole.AUDITOR])


def verify_account_access_for_reading(user: User, account: Account) -> bool:
    """Admin and Auditor can view any account; Account holder can only view their own."""
    if user.role in [UserRole.ADMIN, UserRole.AUDITOR]:
        return True
    return account.user_id == user.id


def verify_account_access_for_movement(user: User, account: Account) -> bool:
    """
    Auditor can NEVER move money (read-only).
    Admin can move or perform administrative adjustments.
    Account holder can only move money from accounts they own.
    """
    if user.role == UserRole.AUDITOR:
        return False
    if user.role == UserRole.ADMIN:
        return True
    return account.user_id == user.id
