from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional
from app.models.user import UserRole


class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=100)
    password: str = Field(..., min_length=6, max_length=72)
    full_name: str = Field(..., min_length=1, max_length=100)
    role: Optional[UserRole] = UserRole.ACCOUNT_HOLDER


class UserLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: str
    full_name: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
