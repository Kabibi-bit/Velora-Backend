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
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        # bcrypt's real, underlying limit is 72 BYTES, not characters -
        # a fundamental property of the algorithm itself (its key
        # schedule only processes the first 72 bytes of input), not a
        # library quirk. Without this explicit check, two genuinely
        # different passwords sharing the same first 72 bytes would
        # hash identically - a real, silent risk this raises loudly
        # against instead, regardless of how the installed bcrypt
        # version itself handles an over-length input.
        raise ValueError("Password is too long (max 72 bytes once UTF-8 encoded)")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")
 
 
def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        # Mirrors the identical guard in hash_password - a password
        # over the real 72-byte limit could never have been the one
        # genuinely hashed in the first place, so this is honestly a
        # non-match, not a case worth passing through to bcrypt itself.
        return False
    try:
        return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))
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
    except Exception:
        # A genuine, final safety net - the two specific exception
        # types above cover the real, documented pyjwt failure modes,
        # but a security-critical token-decode path should never let
        # an unexpected exception type propagate as a raw, unhandled
        # error instead of an honest "invalid token" rejection.
        return None
 
 
def verify_token_belongs_to_user(user_id: str, authorization: str | None) -> dict:
    """The real, shared verification core: a valid, non-expired token
    whose own sub claim genuinely matches the given user_id. Used
    both directly (when a route already has user_id from its own URL
    path) and indirectly (when a route only has some other resource's
    id, and the caller looks up that resource's real owning user_id
    first before calling this)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("sub") != user_id:
        raise HTTPException(status_code=403, detail="This token does not belong to the requested user")
    return payload
 
 
def require_auth_for_user(user_id: str, authorization: str = Header(None)) -> dict:
    """A real, reusable FastAPI dependency for the common case: a
    route whose own URL path already has user_id. Not usable as-is
    for a route that only has some other resource's id (e.g. a
    post_id) - that case needs the resource's real owner looked up
    first, then verify_token_belongs_to_user called directly with
    that real owner's id (see e.g. social.py's edit_post/delete_post).
    """
    return verify_token_belongs_to_user(user_id, authorization)
 
