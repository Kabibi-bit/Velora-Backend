from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
 
from app.db import get_db
from app.models.db_models import User
 
router = APIRouter(prefix="/users", tags=["users"])
 
VALID_ROLES = {"candidate"}
 
 
class UserIn(BaseModel):
    email: EmailStr
    role: str = "candidate"
 
 
@router.post("")
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {VALID_ROLES}")
 
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        return {"user_id": str(existing.id), "status": "already exists", "role": existing.role}
 
    user = User(email=payload.email, role=payload.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": str(user.id), "status": "created", "role": user.role}
 
 
@router.get("/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": str(user.id), "email": user.email, "role": user.role}
 
