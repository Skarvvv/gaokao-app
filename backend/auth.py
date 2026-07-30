"""Authentication Utilities
============================
- Password hashing: bcrypt (direct, no passlib dependency issues)
- JWT token: generation + verification
- FastAPI dependency: get_current_user for protected routes
"""

import bcrypt
import jwt
import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_DAYS
from database import get_db
from models import User
from logging_config import get_logger

logger = get_logger("auth")

# ── Bearer token scheme (auto-adds "Authorization: Bearer xxx" to Swagger UI) ──
security = HTTPBearer()


# ============================================
# Password hashing
# ============================================

def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ============================================
# JWT token
# ============================================

def create_token(user_id: int) -> str:
    """Generate a JWT token for the given user ID."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(days=JWT_EXPIRE_DAYS),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    logger.debug("[AUTH] Token created for user_id=%d (expires in %d days)", user_id, JWT_EXPIRE_DAYS)
    return token


def verify_token(token: str) -> int:
    """Verify a JWT token and return the user ID.

    Raises HTTPException(401) if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
        logger.debug("[AUTH] Token verified: user_id=%d", user_id)
        return user_id
    except jwt.ExpiredSignatureError:
        logger.warning("[AUTH] Token expired (user tried to access with expired token)")
        raise HTTPException(status_code=401, detail="Token expired, please login again")
    except (jwt.InvalidTokenError, KeyError, ValueError) as e:
        logger.warning("[AUTH] Invalid token: %s", e)
        raise HTTPException(status_code=401, detail="Invalid token, please login again")


# ============================================
# FastAPI dependency: get current user
# ============================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency: extract and verify the Bearer token,
    return the User ORM object.

    Usage in route:
        @app.get("/protected")
        async def protected(user: User = Depends(get_current_user)):
            return {"user": user.to_dict()}
    """
    user_id = verify_token(credentials.credentials)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.warning("[AUTH] User not found in DB: user_id=%d", user_id)
        raise HTTPException(status_code=401, detail="User not found")
    logger.debug("[AUTH] Authenticated: user_id=%d, phone=%s", user.id, user.phone)
    return user
