import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

try:
    from .database import get_db
    from .models import User, UserSession
except ImportError:
    from database import get_db
    from models import User, UserSession


# Security Constants
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SESSION_EXPIRATION_DAYS = 7


def hash_password(password: str) -> str:
    """
    Hashes a password using the OWASP-recommended scrypt key derivation function.
    Format: scrypt$16384$8$1$<hex_salt>$<hex_hash>
    """
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, hashed: str) -> bool:
    """
    Verifies a plain password against an scrypt hash using constant-time comparison.
    """
    if not plain_password or not hashed:
        return False
    parts = hashed.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False

    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected_hash = bytes.fromhex(parts[5])

        derived = hashlib.scrypt(
            plain_password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
        )
        return hmac.compare_digest(derived, expected_hash)
    except Exception:
        return False


def create_session(user_id: str, db: Session, days: int = SESSION_EXPIRATION_DAYS) -> Tuple[str, datetime]:
    """
    Generates a secure 32-byte URL-safe session token and records it in the database.
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=days)
    session_record = UserSession(
        token=token,
        user_id=user_id,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
        last_active_at=datetime.utcnow(),
    )
    db.add(session_record)
    db.commit()
    db.refresh(session_record)
    return token, expires_at


def invalidate_session(token: str, db: Session) -> bool:
    """
    Revokes a specific session token from the database.
    """
    if not token:
        return False
    session_record = db.query(UserSession).filter(UserSession.token == token).first()
    if session_record:
        db.delete(session_record)
        db.commit()
        return True
    return False


def invalidate_all_user_sessions(user_id: str, db: Session) -> int:
    """
    Revokes all active sessions for a user (e.g., upon password reset or account deletion).
    """
    count = db.query(UserSession).filter(UserSession.user_id == user_id).delete()
    db.commit()
    return count


def get_token_from_request(
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
) -> Optional[str]:
    """
    Extracts session token from Authorization: Bearer header or session_token cookie.
    """
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    if session_token:
        return session_token.strip()
    return None


def get_current_user_optional(
    request: Request,
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Returns the authenticated User if valid credentials are provided, or None.
    Supports both Authorization: Bearer <token> and HTTP-only session_token cookies.
    """
    token = get_token_from_request(authorization, session_token)
    if not token:
        return None

    session_rec = db.query(UserSession).filter(UserSession.token == token).first()
    if not session_rec:
        return None

    if session_rec.expires_at < datetime.utcnow():
        db.delete(session_rec)
        db.commit()
        return None

    # Update last active timestamp
    session_rec.last_active_at = datetime.utcnow()
    db.commit()

    user = db.query(User).filter(User.username == session_rec.user_id, User.is_active == True).first()
    return user


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency that enforces authentication.
    - If a valid session token is provided, returns that authenticated user.
    - In development mode (ENVIRONMENT != 'production'), if no auth token is passed,
      defaults to 'default_user' to preserve local workflow.
    - If an explicit user is requested or in production mode, unauthenticated calls fail with 401.
    """
    token = get_token_from_request(authorization, session_token)
    if token:
        user = get_current_user_optional(request, authorization, session_token, db)
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    env = os.getenv("ENVIRONMENT", "development").strip().lower()
    if env == "production":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In local development mode, maintain backward compatibility for default_user
    dev_user = db.query(User).filter(User.username == "default_user").first()
    if not dev_user:
        dev_user = User(
            username="default_user",
            email="developer@privatemind.local",
            password_hash=hash_password("DevPassword123!"),
            is_active=True,
            memory_enabled=True,
            auto_extraction=True,
            review_before_save=True,
        )
        db.add(dev_user)
        db.commit()
        db.refresh(dev_user)

    return dev_user
