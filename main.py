import json
import random
import string
from datetime import datetime, timedelta
from typing import List

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import engine, get_db, Base
from models import User, Cafe
from schemas import (
    RegisterRequest, VerifyOTPRequest, ResendOTPRequest,
    LoginRequest, TokenResponse, MessageResponse,
    UserResponse, UpdateProfileRequest,
    CafeCreate, CafeUpdate, CafeResponse,
)
from auth import hash_password, verify_password, create_access_token, get_current_user
from email_service import send_otp_email

# ─── Create all tables on startup ───────────────────────────────

Base.metadata.create_all(bind=engine)

# ─── FastAPI App ────────────────────────────────────────────────

app = FastAPI(
    title="Café Diary API",
    description="Backend API for the Café Diary mobile app",
    version="1.0.0",
)

# Allow requests from the React Native app (any origin for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helper: Generate OTP ──────────────────────────────────────

def generate_otp(length: int = 6) -> str:
    """Generate a random numeric OTP of the given length."""
    return "".join(random.choices(string.digits, k=length))


@app.get("/api/email-status")
def email_status():
    """Debug: check if email service is configured."""
    import os
    key = os.environ.get("RESEND_API_KEY", "")
    return {
        "resend_configured": bool(key),
        "key_prefix": key[:8] + "..." if len(key) > 8 else "NOT SET",
        "render_env": bool(os.environ.get("RENDER")),
    }


@app.get("/api/test-email/{email}")
def test_email(email: str):
    """Debug: send a test email and return raw Resend response."""
    import os
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
    
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        return {"error": "RESEND_API_KEY not set"}
    
    payload = json.dumps({
        "from": "Cafe Diary <onboarding@resend.dev>",
        "to": [email],
        "subject": "Test from Cafe Diary",
        "html": "<h1>Hello! This is a test email from Cafe Diary.</h1>",
    }).encode("utf-8")
    
    req = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    
    try:
        with urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
            return {"status": resp.status, "response": json.loads(body)}
    except HTTPError as e:
        body = e.read().decode()
        return {"status": e.code, "error": json.loads(body)}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  AUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════


@app.post("/api/register", response_model=MessageResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new user account.
    
    Flow:
    1. Check if email already exists
    2. Hash the password
    3. Generate a 6-digit OTP
    4. Create the user with is_verified=False
    5. Return success message with OTP (in production, send via email)
    
    The OTP expires in 10 minutes.
    """
    # Check for existing user with this email
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists",
        )

    # Validate password strength
    if len(req.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters",
        )

    # Generate OTP
    otp = generate_otp(6)
    otp_expires = datetime.utcnow() + timedelta(minutes=10)

    # Create user
    user = User(
        name=req.name,
        email=req.email,
        phone=req.phone,
        password_hash=hash_password(req.password),
        is_verified=False,
        otp_code=otp,
        otp_expires_at=otp_expires,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Send OTP via email
    send_otp_email(req.email, otp, req.name)

    return MessageResponse(
        message=f"Registration successful! A 6-digit verification code has been sent to {req.email}."
    )


@app.post("/api/verify-email", response_model=MessageResponse)
def verify_email(req: VerifyOTPRequest, db: Session = Depends(get_db)):
    """
    Verify user's email using the 6-digit OTP.
    
    Flow:
    1. Find user by email
    2. Check OTP matches and hasn't expired
    3. Mark user as verified
    4. Clear OTP fields
    """
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email",
        )

    if user.is_verified:
        return MessageResponse(message="Email is already verified")

    # Check OTP
    if user.otp_code != req.otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code",
        )

    # Check expiry
    if user.otp_expires_at and datetime.utcnow() > user.otp_expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please request a new one.",
        )

    # Mark as verified
    user.is_verified = True
    user.otp_code = None
    user.otp_expires_at = None
    db.commit()

    return MessageResponse(message="Email verified successfully! You can now sign in.")


@app.post("/api/resend-otp", response_model=MessageResponse)
def resend_otp(req: ResendOTPRequest, db: Session = Depends(get_db)):
    """
    Resend a new OTP to the user's email.
    
    Generates a fresh 6-digit code with a new 10-minute expiry.
    """
    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email",
        )

    if user.is_verified:
        return MessageResponse(message="Email is already verified")

    # Generate new OTP
    otp = generate_otp(6)
    otp_expires = datetime.utcnow() + timedelta(minutes=10)

    user.otp_code = otp
    user.otp_expires_at = otp_expires
    db.commit()

    # Send new OTP via email
    send_otp_email(req.email, otp, user.name)

    return MessageResponse(message=f"A new verification code has been sent to {req.email}")


@app.post("/api/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate a user and return a JWT token.
    
    Flow:
    1. Find user by email
    2. Verify password
    3. Check email is verified
    4. Generate and return JWT access token
    """
    user = db.query(User).filter(User.email == req.email).first()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before signing in",
        )

    token = create_access_token(user.id)

    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


# ═══════════════════════════════════════════════════════════════
#  USER PROFILE ENDPOINTS
# ═══════════════════════════════════════════════════════════════


@app.get("/api/profile", response_model=UserResponse)
def get_profile(current_user: User = Depends(get_current_user)):
    """Get the authenticated user's profile."""
    return current_user


@app.put("/api/profile", response_model=UserResponse)
def update_profile(
    req: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the authenticated user's profile (name, phone)."""
    if req.name is not None:
        current_user.name = req.name
    if req.phone is not None:
        current_user.phone = req.phone

    db.commit()
    db.refresh(current_user)
    return current_user


# ═══════════════════════════════════════════════════════════════
#  CAFE ENDPOINTS
# ═══════════════════════════════════════════════════════════════


@app.get("/api/cafes", response_model=List[CafeResponse])
def get_cafes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all cafes for the authenticated user, newest first."""
    cafes = (
        db.query(Cafe)
        .filter(Cafe.user_id == current_user.id)
        .order_by(Cafe.created_at.desc())
        .all()
    )
    return cafes


@app.post("/api/cafes", response_model=CafeResponse, status_code=201)
def create_cafe(
    req: CafeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new cafe entry for the authenticated user."""
    cafe = Cafe(
        user_id=current_user.id,
        name=req.name,
        city=req.city,
        drink=req.drink,
        rating=req.rating,
        notes=req.notes,
        latitude=req.latitude,
        longitude=req.longitude,
    )
    db.add(cafe)
    db.commit()
    db.refresh(cafe)
    return cafe


@app.put("/api/cafes/{cafe_id}", response_model=CafeResponse)
def update_cafe(
    cafe_id: int,
    req: CafeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing cafe. Only the owner can update."""
    cafe = db.query(Cafe).filter(
        Cafe.id == cafe_id,
        Cafe.user_id == current_user.id,
    ).first()

    if not cafe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cafe not found",
        )

    # Apply only the fields that were provided
    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(cafe, field, value)

    db.commit()
    db.refresh(cafe)
    return cafe


@app.delete("/api/cafes/{cafe_id}", response_model=MessageResponse)
def delete_cafe(
    cafe_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a cafe. Only the owner can delete."""
    cafe = db.query(Cafe).filter(
        Cafe.id == cafe_id,
        Cafe.user_id == current_user.id,
    ).first()

    if not cafe:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cafe not found",
        )

    db.delete(cafe)
    db.commit()
    return MessageResponse(message="Cafe deleted successfully")


# ═══════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ═══════════════════════════════════════════════════════════════


@app.get("/api/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "app": "Café Diary API", "version": "1.0.0"}
