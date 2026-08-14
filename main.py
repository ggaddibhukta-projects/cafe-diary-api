import json
import random
import string
from datetime import datetime, timedelta
from typing import List

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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
from email_service import send_otp_email, last_email_result

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

@app.get("/api/last-email-result")
def get_last_email_result():
    """Debug: shows what happened during the last email send attempt."""
    from email_service import last_email_result as result
    return result


@app.delete("/api/admin/delete-all-users")
def delete_all_users(db: Session = Depends(get_db)):
    """Admin: delete all users from the database."""
    count = db.query(User).count()
    db.query(User).delete()
    db.commit()
    return {"message": f"Deleted {count} users"}


@app.post("/api/admin/reset-db")
def reset_database():
    """Admin: drop and recreate all tables (fresh schema)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return {"message": "Database tables dropped and recreated successfully"}


@app.get("/api/admin/db-stats")
def db_stats(db: Session = Depends(get_db)):
    """Admin: view database stats."""
    user_count = db.query(User).count()
    cafe_count = db.query(Cafe).count()
    users = db.query(User).all()
    return {
        "users": user_count,
        "cafes": cafe_count,
        "user_list": [{"id": u.id, "name": u.name, "email": u.email} for u in users],
    }


@app.get("/api/admin/migrate")
def migrate_db(db: Session = Depends(get_db)):
    """Temporary route to add image_url column."""
    from sqlalchemy import text
    try:
        db.execute(text("ALTER TABLE cafes ADD COLUMN image_url VARCHAR(500);"))
        db.commit()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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

    # Create user (verified immediately — no OTP needed)
    user = User(
        name=req.name,
        email=req.email,
        phone=req.phone,
        password_hash=hash_password(req.password),
        is_verified=True,
        otp_code=None,
        otp_expires_at=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return MessageResponse(
        message="Account created successfully! You can now sign in."
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

    # Email verification check removed — accounts are auto-verified

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
        image_url=req.image_url,
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
#  PUBLIC SHARE ENDPOINT
# ═══════════════════════════════════════════════════════════════

@app.get("/shared/{user_id}/{city}", response_class=HTMLResponse)
def get_shared_city_cafes(user_id: int, city: str, db: Session = Depends(get_db)):
    """Public endpoint to view a user's cafes for a specific city."""
    import urllib.parse
    decoded_city = urllib.parse.unquote(city)
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    cafes = (
        db.query(Cafe)
        .filter(Cafe.user_id == user_id)
        .filter(Cafe.city == decoded_city)
        .order_by(Cafe.created_at.desc())
        .all()
    )
    
    # Generate HTML
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{user.name}'s Cafés in {decoded_city}</title>
        <style>
            :root {{
                --bg: #F7F5F0;
                --text-primary: #1C1917;
                --text-secondary: #57534E;
                --card-bg: #FFFFFF;
                --border: #E7E5E4;
                --primary: #44403C;
                --radius: 12px;
                --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            }}
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: var(--bg);
                color: var(--text-primary);
                line-height: 1.5;
                padding: 20px;
                -webkit-font-smoothing: antialiased;
            }}
            .container {{
                max-width: 800px;
                margin: 0 auto;
                padding-top: 40px;
                padding-bottom: 60px;
            }}
            .header {{
                text-align: center;
                margin-bottom: 40px;
            }}
            .header h1 {{
                font-size: 2.5rem;
                font-weight: 800;
                margin-bottom: 8px;
                letter-spacing: -0.02em;
            }}
            .header p {{
                color: var(--text-secondary);
                font-size: 1.125rem;
            }}
            .empty-state {{
                text-align: center;
                padding: 40px;
                background: var(--card-bg);
                border-radius: var(--radius);
                border: 1px dashed var(--border);
                color: var(--text-secondary);
            }}
            .grid {{
                display: grid;
                grid-template-columns: 1fr;
                gap: 24px;
            }}
            @media (min-width: 640px) {{
                .grid {{ grid-template-columns: repeat(2, 1fr); }}
            }}
            .card {{
                background: var(--card-bg);
                border-radius: var(--radius);
                overflow: hidden;
                box-shadow: var(--shadow);
                border: 1px solid var(--border);
                transition: transform 0.2s ease, box-shadow 0.2s ease;
                display: flex;
                flex-direction: column;
            }}
            .card:hover {{
                transform: translateY(-4px);
                box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
            }}
            .card-image-wrapper {{
                width: 100%;
                padding-top: 66.66%; /* 3:2 Aspect Ratio */
                position: relative;
                background-color: #E6E0D4;
            }}
            .card-image {{
                position: absolute;
                top: 0; left: 0; width: 100%; height: 100%;
                object-fit: cover;
            }}
            .card-image-fallback {{
                position: absolute;
                top: 0; left: 0; width: 100%; height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 3rem;
                color: rgba(0,0,0,0.1);
            }}
            .card-content {{
                padding: 20px;
                flex: 1;
                display: flex;
                flex-direction: column;
            }}
            .card-title {{
                font-size: 1.25rem;
                font-weight: 700;
                margin-bottom: 4px;
            }}
            .card-rating {{
                display: inline-flex;
                align-items: center;
                gap: 4px;
                font-weight: 600;
                color: #CA8A04;
                margin-bottom: 12px;
                font-size: 0.9rem;
            }}
            .card-meta {{
                font-size: 0.9rem;
                color: var(--text-secondary);
                margin-bottom: 12px;
                display: flex;
                flex-direction: column;
                gap: 4px;
            }}
            .card-meta-item {{
                display: flex;
                align-items: center;
                gap: 6px;
            }}
            .card-notes {{
                font-size: 0.95rem;
                color: var(--text-primary);
                margin-bottom: 20px;
                flex: 1;
            }}
            .map-btn {{
                display: inline-block;
                width: 100%;
                text-align: center;
                padding: 10px 16px;
                background-color: var(--primary);
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                font-size: 0.95rem;
                transition: background-color 0.2s;
            }}
            .map-btn:hover {{
                background-color: #292524;
            }}
            .footer {{
                text-align: center;
                margin-top: 60px;
                padding-top: 20px;
                border-top: 1px solid var(--border);
                color: var(--text-secondary);
                font-size: 0.9rem;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>{user.name}'s Cafés</h1>
                <p>{len(cafes)} saved in {decoded_city}</p>
            </div>
            
            <div class="grid">
    """
    
    if not cafes:
        html_content += f"""
            </div>
            <div class="empty-state">
                <p>No cafes found for this city yet.</p>
            </div>
        """
    else:
        for cafe in cafes:
            # Safely handle potential None values
            rating_str = f"★ {cafe.rating:.1f}" if cafe.rating else "No rating"
            drink_str = f"""
                <div class="card-meta-item">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 8h1a4 4 0 1 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4Z"/><line x1="6" x2="6" y1="2" y2="4"/><line x1="10" x2="10" y1="2" y2="4"/><line x1="14" x2="14" y1="2" y2="4"/></svg>
                    <span>{cafe.drink}</span>
                </div>
            """ if cafe.drink else ""
            
            notes_str = f'<p class="card-notes">"{cafe.notes}"</p>' if cafe.notes else '<p class="card-notes"></p>'
            
            image_src = cafe.image_url.split(',')[0] if cafe.image_url else None
            image_html = f'<img src="{image_src}" alt="{cafe.name}" class="card-image">' if image_src else '<div class="card-image-fallback">☕</div>'
            
            map_link = ""
            if cafe.latitude and cafe.longitude:
                map_url = f"https://www.google.com/maps/search/?api=1&query={cafe.latitude},{cafe.longitude}"
                map_link = f'<a href="{map_url}" target="_blank" rel="noopener noreferrer" class="map-btn">View on Map</a>'
            else:
                map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(cafe.name + ' ' + decoded_city)}"
                map_link = f'<a href="{map_url}" target="_blank" rel="noopener noreferrer" class="map-btn">Search on Map</a>'

            html_content += f"""
                <div class="card">
                    <div class="card-image-wrapper">
                        {image_html}
                    </div>
                    <div class="card-content">
                        <h2 class="card-title">{cafe.name}</h2>
                        <div class="card-rating">{rating_str}</div>
                        
                        <div class="card-meta">
                            {drink_str}
                        </div>
                        
                        {notes_str}
                        
                        {map_link}
                    </div>
                </div>
            """
            
        html_content += "</div>"
        
    html_content += """
            <div class="footer">
                Shared via Café Diary
            </div>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@app.get("/shared/{user_id}/cafe/{cafe_id}", response_class=HTMLResponse)
def get_shared_single_cafe(user_id: int, cafe_id: int, db: Session = Depends(get_db)):
    """Public endpoint to view a single shared cafe."""
    import urllib.parse
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    cafe = (
        db.query(Cafe)
        .filter(Cafe.user_id == user_id)
        .filter(Cafe.id == cafe_id)
        .first()
    )
    
    if not cafe:
        raise HTTPException(status_code=404, detail="Cafe not found")
    
    rating_str = f"★ {cafe.rating:.1f}" if cafe.rating else "No rating"
    drink_str = f"""
        <div class="card-meta-item">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 8h1a4 4 0 1 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4Z"/><line x1="6" x2="6" y1="2" y2="4"/><line x1="10" x2="10" y1="2" y2="4"/><line x1="14" x2="14" y1="2" y2="4"/></svg>
            <span>{cafe.drink}</span>
        </div>
    """ if cafe.drink else ""
    
    notes_str = f'<p class="card-notes">"{cafe.notes}"</p>' if cafe.notes else '<p class="card-notes"></p>'
    
    images = [u.strip() for u in cafe.image_url.split(',') if u.strip() and u.strip() != 'null'] if cafe.image_url else []
    if images:
        imgs_html = ''.join(f'<img src="{u}" alt="{cafe.name}" class="gallery-img">' for u in images)
        dots_html = ''.join(f'<span class="dot" onclick="goTo({i})"></span>' for i in range(len(images))) if len(images) > 1 else ''
        image_html = f'<div class="gallery" id="gallery">{imgs_html}</div><div class="dots" id="dots">{dots_html}</div>'
    else:
        image_html = '<div class="card-image-fallback">☕</div>'
    
    map_link = ""
    if cafe.latitude and cafe.longitude:
        map_url = f"https://www.google.com/maps/search/?api=1&query={cafe.latitude},{cafe.longitude}"
        map_link = f'<a href="{map_url}" target="_blank" rel="noopener noreferrer" class="map-btn">View on Map</a>'
    else:
        map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(cafe.name + ' ' + cafe.city)}"
        map_link = f'<a href="{map_url}" target="_blank" rel="noopener noreferrer" class="map-btn">Search on Map</a>'
        
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{cafe.name} - Shared by {user.name}</title>
        <style>
            :root {{
                --bg: #F7F5F0;
                --text-primary: #1C1917;
                --text-secondary: #57534E;
                --card-bg: #FFFFFF;
                --border: #E7E5E4;
                --primary: #44403C;
                --radius: 12px;
                --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            }}
            * {{ box-sizing: border-box; margin: 0; padding: 0; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: var(--bg);
                color: var(--text-primary);
                line-height: 1.5;
                padding: 20px;
                -webkit-font-smoothing: antialiased;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding-top: 40px;
                padding-bottom: 60px;
            }}
            .header {{
                text-align: center;
                margin-bottom: 40px;
            }}
            .header h1 {{
                font-size: 2.5rem;
                font-weight: 800;
                margin-bottom: 8px;
                letter-spacing: -0.02em;
            }}
            .header p {{
                color: var(--text-secondary);
                font-size: 1.125rem;
            }}
            .card {{
                background: var(--card-bg);
                border-radius: var(--radius);
                overflow: hidden;
                box-shadow: var(--shadow);
                border: 1px solid var(--border);
                display: flex;
                flex-direction: column;
            }}
            .gallery-container {{
                position: relative;
                width: 100%;
                background-color: #E6E0D4;
                overflow: hidden;
            }}
            .gallery {{
                display: flex;
                overflow-x: auto;
                scroll-snap-type: x mandatory;
                -webkit-overflow-scrolling: touch;
                scrollbar-width: none;
            }}
            .gallery::-webkit-scrollbar {{ display: none; }}
            .gallery-img {{
                flex: 0 0 100%;
                width: 100%;
                height: 300px;
                object-fit: cover;
                scroll-snap-align: start;
            }}
            .dots {{
                display: flex;
                justify-content: center;
                gap: 6px;
                padding: 10px 0;
                background: #E6E0D4;
            }}
            .dot {{
                width: 7px;
                height: 7px;
                border-radius: 50%;
                background: rgba(0,0,0,0.2);
                cursor: pointer;
                transition: background 0.2s;
            }}
            .dot.active {{
                background: rgba(0,0,0,0.6);
            }}
            .card-image-fallback {{
                width: 100%;
                height: 300px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 4rem;
                color: rgba(0,0,0,0.1);
            }}
            .card-content {{
                padding: 24px;
                display: flex;
                flex-direction: column;
            }}
            .card-title {{
                font-size: 1.5rem;
                font-weight: 700;
                margin-bottom: 4px;
            }}
            .card-rating {{
                display: inline-flex;
                align-items: center;
                gap: 4px;
                font-weight: 600;
                color: #CA8A04;
                margin-bottom: 12px;
                font-size: 1rem;
            }}
            .card-meta {{
                font-size: 1rem;
                color: var(--text-secondary);
                margin-bottom: 16px;
                display: flex;
                flex-direction: column;
                gap: 6px;
            }}
            .card-meta-item {{
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .card-notes {{
                font-size: 1.05rem;
                color: var(--text-primary);
                margin-bottom: 24px;
                line-height: 1.6;
            }}
            .map-btn {{
                display: inline-block;
                width: 100%;
                text-align: center;
                padding: 12px 16px;
                background-color: var(--primary);
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                font-size: 1rem;
                transition: background-color 0.2s;
            }}
            .map-btn:hover {{
                background-color: #292524;
            }}
            .footer {{
                text-align: center;
                margin-top: 60px;
                padding-top: 20px;
                border-top: 1px solid var(--border);
                color: var(--text-secondary);
                font-size: 0.9rem;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>{user.name}'s Café Pick</h1>
                <p>Shared via Café Diary</p>
            </div>
            
            <div class="card">
                <div class="gallery-container">
                    {image_html}
                </div>
                <div class="card-content">
                    <h2 class="card-title">{cafe.name}</h2>
                    <div class="card-rating">{rating_str}</div>
                    
                    <div class="card-meta">
                        {drink_str}
                        <div class="card-meta-item">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>
                            <span>{cafe.city}</span>
                        </div>
                    </div>
                    
                    {notes_str}
                    
                    {map_link}
                </div>
            </div>
            
            <div class="footer">
                Download Café Diary to save your own spots
            </div>
        </div>
        <!-- INJECT_SCRIPTS -->
    </body>
    </html>
    """

    # Inject gallery scroll JS for multiple images
    if len(images) > 1:
        gallery_js = """
    <script>
        var gallery = document.getElementById('gallery');
        var dots = document.querySelectorAll('.dot');
        function updateDots(idx) {
            dots.forEach(function(d, i) { d.classList.toggle('active', i === idx); });
        }
        updateDots(0);
        gallery.addEventListener('scroll', function() {
            var idx = Math.round(gallery.scrollLeft / gallery.clientWidth);
            updateDots(idx);
        });
        function goTo(idx) {
            gallery.scrollTo({ left: idx * gallery.clientWidth, behavior: 'smooth' });
            updateDots(idx);
        }
    </script>"""
        html_content = html_content.replace('<!-- INJECT_SCRIPTS -->', gallery_js)

    return HTMLResponse(content=html_content)


# ═══════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ═══════════════════════════════════════════════════════════════


@app.get("/api/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "app": "Café Diary API", "version": "1.0.0"}
