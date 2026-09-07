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
    The scan scheduler (scheduler.py) already writes Notification
    rows directly into the same database session when a cycle finds
    new matches or auto-drafts something - via direct model
    instantiation, not by calling this HTTP endpoint, since that's
    the correct, efficient choice for internal server-side code. This
    endpoint exists for anything that genuinely needs to create a
    notification over HTTP instead.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    note = Notification(user_id=payload.user_id, type=payload.type, title=payload.title, detail=payload.detail)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"status": "created", "notification_id": str(note.id)}
 
 
@router.get("/{user_id}")
def get_notifications(user_id: str, db: Session = Depends(get_db)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
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
    import uuid as uuid_module
    try:
        uuid_module.UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Notification not found")
    note = db.query(Notification).filter(Notification.id == notification_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Notification not found")
    note.is_read = True
    db.commit()
    return {"status": "marked read"}
 
 
@router.post("/{user_id}/mark-all-read")
def mark_all_read(user_id: str, db: Session = Depends(get_db)):
    """Bulk counterpart to mark_read above - mirrors the frontend's
    own markAllNotificationsRead() exactly. Genuine gap this closes:
    the frontend already offered this action, but the backend only
    ever supported marking one notification read at a time.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .update({"is_read": True})
    )
    db.commit()
    return {"status": "marked all read", "updated_count": updated}
 
 
@router.delete("/{user_id}")
def clear_notifications(user_id: str, db: Session = Depends(get_db)):
    """Mirrors the frontend's own clearNotifications() exactly - the
    same genuine gap as mark_all_read above, a real frontend action
    with no backend counterpart until now.
    """
    import uuid as uuid_module
    try:
        uuid_module.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    deleted = db.query(Notification).filter(Notification.user_id == user_id).delete()
    db.commit()
    return {"status": "cleared", "deleted_count": deleted}
 
