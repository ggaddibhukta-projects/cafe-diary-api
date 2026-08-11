from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from database import Base


class User(Base):
    """User account model — stores credentials, profile info, and OTP for email verification."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=True)
    password_hash = Column(String(255), nullable=False)

    # Email verification via OTP
    is_verified = Column(Boolean, default=False)
    otp_code = Column(String(6), nullable=True)       # 6-digit OTP
    otp_expires_at = Column(DateTime, nullable=True)   # OTP expiry time

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship: one user has many cafes
    cafes = relationship("Cafe", back_populates="owner", cascade="all, delete-orphan")


class Cafe(Base):
    """Cafe entry model — each cafe belongs to a user."""
    __tablename__ = "cafes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    name = Column(String(200), nullable=False)
    city = Column(String(200), nullable=False, default="Unknown")
    drink = Column(String(200), nullable=True)
    rating = Column(Float, default=0.0)
    notes = Column(Text, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    is_saved = Column(Boolean, default=False)
    is_shared = Column(Boolean, default=False)
    image_url = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship back to user
    owner = relationship("User", back_populates="cafes")
