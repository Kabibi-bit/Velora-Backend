from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
 
from app.db import get_db
from app.models.db_models import Notification
 
router = APIRouter(prefix="/notifications", tags=["notifications"])
 
 
class NotificationIn(BaseModel):
    user_id: str
    type: str
    title: str
    detail: str | None = None
 
 
@router.post("")
def create_notification(payload: NotificationIn, db: Session = Depends(get_db)):
    """Records a real notification - this is what backs the frontend's
    Inbox page, which was previously only in browser localStorage.
    In production, the scan scheduler (scheduler.py) would call this
    directly whenever a cycle finds new matches, instead of the
    frontend simulating it.
    """
    note = Notification(user_id=payload.user_id, type=payload.type, title=payload.title, detail=payload.detail)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"status": "created", "notification_id": str(note.id)}
 
 
@router.get("/{user_id}")
def get_notifications(user_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(desc(Notification.created_at))
        .limit(50)
        .all()
    )
    return [
        {"id": str(n.id), "type": n.type, "title": n.title, "detail": n.detail, "is_read": n.is_read, "created_at": n.created_at.isoformat()}
        for n in rows
    ]
 
 
@router.post("/{notification_id}/read")
def mark_read(notification_id: str, db: Session = Depends(get_db)):
    note = db.query(Notification).filter(Notification.id == notification_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Notification not found")
    note.is_read = True
    db.commit()
    return {"status": "marked read"}
 
