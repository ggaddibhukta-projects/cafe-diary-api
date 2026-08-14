from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


# ─── Auth Schemas ───────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """Request body for user registration."""
    name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str


class VerifyOTPRequest(BaseModel):
    """Request body for OTP email verification."""
    email: EmailStr
    otp: str


class ResendOTPRequest(BaseModel):
    """Request body to resend OTP."""
    email: EmailStr


class LoginRequest(BaseModel):
    """Request body for login."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Response after successful login."""
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


# ─── User Schemas ───────────────────────────────────────────────

class UserResponse(BaseModel):
    """User profile response (no sensitive fields)."""
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    """Request body to update user profile."""
    name: Optional[str] = None
    phone: Optional[str] = None


# ─── Cafe Schemas ───────────────────────────────────────────────

class CafeCreate(BaseModel):
    """Request body to create a new cafe."""
    name: str
    city: str = "Unknown"
    drink: Optional[str] = None
    rating: float = Field(default=0.0, ge=0.0, le=5.0)
    notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    image_url: Optional[str] = None


class CafeUpdate(BaseModel):
    """Request body to update a cafe."""
    name: Optional[str] = None
    city: Optional[str] = None
    drink: Optional[str] = None
    rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_saved: Optional[bool] = None
    is_shared: Optional[bool] = None
    image_url: Optional[str] = None


class CafeResponse(BaseModel):
    """Cafe response object."""
    id: int
    name: str
    city: str
    drink: Optional[str] = None
    rating: float
    notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_saved: bool
    is_shared: bool = False
    image_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Resolve forward reference
TokenResponse.model_rebuild()
