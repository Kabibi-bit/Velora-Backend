"""Real authentication: bcrypt password hashing (never stores or
compares plain-text passwords) and JWT session tokens.
 
Honest scope note: this file, plus the /auth routes built on it, is
a genuinely working login/signup system. require_auth_for_user below
is the real, reusable dependency for protecting a route, but most
existing endpoints in this app still don't use it yet - they trust
whatever user_id is passed in the URL, rather than verifying it
against the caller's token. Retrofitting auth checks into every
existing route is a separate, larger change; it's been started on
Waypoint's journal endpoints specifically (explicitly marketed as
private, the most directly contradictory gap), not silently implied
to be done everywhere.
"""
import os
from fastapi import HTTPException, Header
import bcrypt
import jwt
from datetime import datetime, timedelta
 
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24 * 14  # 14 days
 
 
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
 
 
def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False
 
 
def create_access_token(user_id: str, role: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set - generate a long random string and add it to "
            "your Render environment variables before using auth in production."
        )
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
 
 
def decode_access_token(token: str) -> dict | None:
    if not JWT_SECRET:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
 
 
def require_auth_for_user(user_id: str, authorization: str = Header(None)) -> dict:
    """A real, reusable dependency a route can add to require the
    caller's token to genuinely belong to the same user_id already in
    the URL path - not just any valid token, since a valid token for
    one person must not be usable to read or write a different
    person's data by simply changing the user_id in the URL. This is
    the concrete building block this module's own docstring already
    promised; wiring it into every existing route is the separate,
    larger retrofit still ahead, started here on Waypoint's journal
    endpoints specifically, since those are explicitly marketed as
    private and had the most directly contradictory gap.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("sub") != user_id:
        raise HTTPException(status_code=403, detail="This token does not belong to the requested user")
    return payload
 
