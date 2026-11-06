from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.user import User, UserRole
from app.models.account import Account, AccountType, AccountStatus
from app.core.security import hash_password, verify_password, create_access_token
from app.schemas.auth import UserRegisterRequest, UserLoginRequest, TokenResponse
from app.services.audit_service import AuditService


class AuthService:
    @staticmethod
    def register_user(db: Session, request: UserRegisterRequest, ip_address: Optional[str] = None) -> User:
        # Check if username exists
        existing_user = db.query(User).filter(User.username == request.username).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is already taken.",
            )

        existing_email = db.query(User).filter(User.email == request.email).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already registered.",
            )

        new_user = User(
            username=request.username,
            email=request.email,
            hashed_password=hash_password(request.password),
            full_name=request.full_name,
            role=request.role or UserRole.ACCOUNT_HOLDER,
            is_active=True,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        # Audit event
        AuditService.log_event(
            db=db,
            action="USER_REGISTERED",
            user_id=new_user.id,
            entity_type="USER",
            entity_id=str(new_user.id),
            ip_address=ip_address,
            details={"username": new_user.username, "role": new_user.role.value},
        )
        db.commit()

        # Automatically open a default customer account if account_holder
        if new_user.role == UserRole.ACCOUNT_HOLDER:
            from app.services.account_service import AccountService
            AccountService.create_account(
                db=db,
                user_id=new_user.id,
                initial_deposit=Decimal("1000.0000"),  # Starter deposit
                currency="INR",
            )

        return new_user

    @staticmethod
    def login_user(db: Session, request: UserLoginRequest, ip_address: Optional[str] = None) -> TokenResponse:
        user = db.query(User).filter(User.username == request.username).first()
        if not user or not verify_password(request.password, user.hashed_password):
            AuditService.log_event(
                db=db,
                action="LOGIN_FAILED",
                user_id=user.id if user else None,
                entity_type="USER",
                entity_id=request.username,
                ip_address=ip_address,
                details={"reason": "INVALID_CREDENTIALS"},
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated.",
            )

        access_token = create_access_token(
            data={"sub": user.username, "user_id": user.id, "role": user.role.value}
        )

        AuditService.log_event(
            db=db,
            action="LOGIN_SUCCESS",
            user_id=user.id,
            entity_type="USER",
            entity_id=str(user.id),
            ip_address=ip_address,
            details={"role": user.role.value},
        )
        db.commit()

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user_id=user.id,
            username=user.username,
            role=user.role.value,
            full_name=user.full_name,
        )

    @staticmethod
    def seed_initial_data(db: Session) -> None:
        """Seeds standard demo roles & accounts if database is empty"""
        admin_user = db.query(User).filter(User.username == "admin").first()
        if not admin_user:
            admin_user = User(
                username="admin",
                email="admin@ledgerline.com",
                hashed_password=hash_password("AdminPassword123!"),
                full_name="System Administrator",
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

        auditor_user = db.query(User).filter(User.username == "auditor").first()
        if not auditor_user:
            auditor_user = User(
                username="auditor",
                email="auditor@ledgerline.com",
                hashed_password=hash_password("AuditorPassword123!"),
                full_name="Compliance Auditor",
                role=UserRole.AUDITOR,
                is_active=True,
            )
            db.add(auditor_user)
            db.commit()
            db.refresh(auditor_user)

        alice = db.query(User).filter(User.username == "alice").first()
        if not alice:
            alice = User(
                username="alice",
                email="alice@ledgerline.com",
                hashed_password=hash_password("AlicePassword123!"),
                full_name="Alice Smith",
                role=UserRole.ACCOUNT_HOLDER,
                is_active=True,
            )
            db.add(alice)
            db.commit()
            db.refresh(alice)

            from app.services.account_service import AccountService
            AccountService.create_account(
                db=db,
                user_id=alice.id,
                account_number="ACC-ALICE-101",
                initial_deposit=Decimal("5000.0000"),
                currency="INR",
            )

        bob = db.query(User).filter(User.username == "bob").first()
        if not bob:
            bob = User(
                username="bob",
                email="bob@ledgerline.com",
                hashed_password=hash_password("BobPassword123!"),
                full_name="Bob Jones",
                role=UserRole.ACCOUNT_HOLDER,
                is_active=True,
            )
            db.add(bob)
            db.commit()
            db.refresh(bob)

            from app.services.account_service import AccountService
            AccountService.create_account(
                db=db,
                user_id=bob.id,
                account_number="ACC-BOB-202",
                initial_deposit=Decimal("2500.0000"),
                currency="INR",
            )

