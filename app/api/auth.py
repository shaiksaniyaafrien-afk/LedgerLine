from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse)
def register(request: UserRegisterRequest, req: Request, db: Session = Depends(get_db)):
    ip = req.client.host if req.client else None
    return AuthService.register_user(db, request, ip_address=ip)


@router.post("/login", response_model=TokenResponse)
def login(request: UserLoginRequest, req: Request, db: Session = Depends(get_db)):
    ip = req.client.host if req.client else None
    return AuthService.login_user(db, request, ip_address=ip)


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(current_user: User = Depends(get_current_user)):
    return current_user
