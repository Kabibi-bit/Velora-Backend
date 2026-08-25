"""Real authentication: bcrypt password hashing (never stores or
compares plain-text passwords) and JWT session tokens.
 
Honest scope note: this file, plus the /auth routes built on it, is
a genuinely working login/signup system. What it does NOT yet do is
protect every other existing endpoint in this app - those still
trust whatever user_id is passed in the URL, rather than verifying
it against the caller's token. Retrofitting auth checks into every
existing route is a separate, larger change, intentionally left out
here rather than silently implied to be done.
"""
import os
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
 
