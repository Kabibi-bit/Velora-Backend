from fastapi import APIRouter, HTTPException, Depends, Header, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import User
from app.services.auth import hash_password, verify_password, create_access_token, decode_access_token, dummy_password_hash
from app.services.rate_limit import check_login_not_throttled, record_login_failure
 
router = APIRouter(prefix="/auth", tags=["auth"])
 
VALID_ROLES = {"candidate"}
 
 
def _client_ip(request: Request) -> str:
    """The real client IP. Behind Render's proxy the direct peer is the proxy,
    so the genuine client is the FIRST entry of X-Forwarded-For; fall back to the
    direct peer when the header is absent (local/dev). Only used as a throttle
    key - a spoofed value just buckets an attacker under a key they chose, which
    the per-email limit still covers."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
 
 
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    role: str = Field(default="candidate", max_length=40)
 
 
@router.post("/signup")
def signup(payload: SignupIn, db: Session = Depends(get_db)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {VALID_ROLES}")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if len(payload.password.encode("utf-8")) > 72:
        # bcrypt silently truncates and only ever hashes the first 72
        # bytes of a password - confirmed directly against the real
        # bcrypt.hashpw call this uses, with no truncation protection
        # of its own. Without this check, anything past 72 bytes is
        # silently ignored for authentication: a long password offers
        # no more real protection than its first 72 bytes, and two
        # genuinely different passwords sharing that same prefix would
        # be treated as interchangeable. Checked in bytes, not
        # characters, since multi-byte UTF-8 characters make those
        # genuinely different counts.
        raise HTTPException(status_code=400, detail="Password is too long (max 72 bytes) - longer passwords are silently truncated and would offer no additional real protection")
 
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists - try logging in instead")
 
    user = User(email=payload.email, password_hash=hash_password(payload.password), role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
 
    token = create_access_token(str(user.id), user.role)
    return {"user_id": str(user.id), "email": user.email, "role": user.role, "access_token": token}
 
 
class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
 
 
@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    # Brute-force throttle FIRST: reject (429) if this email or client IP has
    # already hit the failed-login ceiling for the current hour, before spending
    # a DB lookup or bcrypt on the attempt. Only genuine failures below consume
    # the budget, so a successful login never throttles the real user. Fails open.
    ip = _client_ip(request)
    check_login_not_throttled(db, payload.email, ip)
 
    user = db.query(User).filter(User.email == payload.email).first()
    # Always run a real bcrypt verify - against the user's hash, or a dummy hash
    # of equal cost when the email is unknown - so response time doesn't reveal
    # whether an account exists (email-enumeration timing side-channel). The
    # dummy path always yields False; the generic error below covers both cases.
    password_ok = verify_password(payload.password, user.password_hash if user else dummy_password_hash())
    if not user or not password_ok:
        record_login_failure(db, payload.email, ip)  # count this genuine failure toward the hourly ceiling
        raise HTTPException(status_code=401, detail="Incorrect email or password")
 
    token = create_access_token(str(user.id), user.role)
    return {"user_id": str(user.id), "email": user.email, "role": user.role, "access_token": token}
 
 
@router.get("/me")
def get_me(authorization: str = Header(None), db: Session = Depends(get_db)):
    """Validates a bearer token and returns the current user - the
    building block for gating any endpoint (or the frontend) behind
    a real logged-in session.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
 
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return {"user_id": str(user.id), "email": user.email, "role": user.role}
 
