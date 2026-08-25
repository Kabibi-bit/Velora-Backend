from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import User
from app.services.auth import hash_password, verify_password, create_access_token, decode_access_token
 
router = APIRouter(prefix="/auth", tags=["auth"])
 
VALID_ROLES = {"candidate", "business", "tutor", "athlete"}
 
 
class SignupIn(BaseModel):
    email: EmailStr
    password: str
    role: str = "candidate"
 
 
@router.post("/signup")
def signup(payload: SignupIn, db: Session = Depends(get_db)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {VALID_ROLES}")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
 
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
    password: str
 
 
@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
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
 
