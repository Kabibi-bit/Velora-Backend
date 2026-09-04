import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
import anthropic
 
from app.db import get_db
from app.models.db_models import SocialPost
from app.services.auth import require_auth_for_user, verify_token_belongs_to_user
from app.services.social import reflect_on_journal_entry, reflect_on_entry_pattern
 
router = APIRouter(prefix="/social", tags=["social"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class PostIn(BaseModel):
    user_id: str
    body: str
    video_url: str | None = None
    tag_value: str | None = None
    tag_label: str | None = None
 
 
@router.post("/posts")
def create_post(payload: PostIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """Adds an entry to the user's own private progress journal.
    Works the same way for all 3 roles - tag_value/tag_label are
    generic (a roadmap stage for candidate/athlete, a teaching phase
    for tutor). video_url is a link to wherever the person already
    hosts their video (YouTube, Loom, etc.) - no upload/hosting is
    done here.
    """
    verify_token_belongs_to_user(payload.user_id, authorization)
    if not payload.body or not payload.body.strip():
        raise HTTPException(status_code=400, detail="Entry body cannot be empty")
    post = SocialPost(
        user_id=payload.user_id, body=payload.body.strip(), video_url=payload.video_url,
        tag_value=payload.tag_value, tag_label=payload.tag_label,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"post_id": str(post.id), "status": "created"}
 
 
def _serialize_post(p: SocialPost) -> dict:
    return {
        "post_id": str(p.id),
        "body": p.body,
        "video_url": p.video_url,
        "tag_value": p.tag_value,
        "tag_label": p.tag_label,
        "created_at": p.created_at.isoformat(),
        "edited_at": p.edited_at.isoformat() if p.edited_at else None,
    }
 
 
@router.get("/posts/{user_id}")
def list_journal(user_id: str, search: str | None = None, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """Lists a user's own journal entries, most recent first. This is
    a private journal, not a feed - it never returns another user's
    entries. Optional `search` filters to entries whose body or tag
    label contains the given text (case-insensitive) - mirrors the
    frontend's own search exactly, done server-side instead of
    filtering a fetched batch client-side.
    """
    query = db.query(SocialPost).filter(SocialPost.user_id == user_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(or_(SocialPost.body.ilike(term), SocialPost.tag_label.ilike(term)))
    rows = query.order_by(desc(SocialPost.created_at)).limit(100).all()
    return [_serialize_post(p) for p in rows]
 
 
class EditPostIn(BaseModel):
    body: str
 
 
@router.patch("/posts/{post_id}")
def edit_post(post_id: str, payload: EditPostIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    verify_token_belongs_to_user(str(post.user_id), authorization)
    if not payload.body or not payload.body.strip():
        raise HTTPException(status_code=400, detail="Entry body cannot be empty")
    post.body = payload.body.strip()
    post.edited_at = datetime.utcnow()
    db.commit()
    return {"status": "updated"}
 
 
@router.delete("/posts/{post_id}")
def delete_post(post_id: str, db: Session = Depends(get_db), authorization: str = Header(None)):
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    verify_token_belongs_to_user(str(post.user_id), authorization)
    db.delete(post)
    db.commit()
    return {"status": "deleted"}
 
 
class ReflectIn(BaseModel):
    focus: str
    context_summary: str | None = None
 
 
@router.post("/posts/{post_id}/reflect")
def reflect_on_post(post_id: str, payload: ReflectIn, db: Session = Depends(get_db), authorization: str = Header(None)):
    """An honest, specific AI reflection on ONE journal entry. Takes
    focus/context_summary directly in the request rather than looking
    up a stored profile, since only candidates have a Profile table -
    athlete/tutor context has stayed frontend-only so far, the same
    honest gap as the rest of those roles' features.
    """
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    verify_token_belongs_to_user(str(post.user_id), authorization)
    try:
        reflection = reflect_on_journal_entry(client, payload.focus, payload.context_summary, post.body, post.tag_label)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate a reflection just now - try again. ({e})")
    return {"post_id": post_id, "reflection": reflection}
 
 
class ReflectPatternIn(BaseModel):
    focus: str
    context_summary: str | None = None
    limit: int = 5
 
 
@router.post("/posts/{user_id}/reflect-pattern")
def reflect_pattern(user_id: str, payload: ReflectPatternIn, db: Session = Depends(get_db), _auth: dict = Depends(require_auth_for_user)):
    """The genuinely more valuable reflection - looks across the
    user's last several entries together for a real pattern, instead
    of restating one entry back at them.
    """
    rows = (
        db.query(SocialPost)
        .filter(SocialPost.user_id == user_id)
        .order_by(desc(SocialPost.created_at))
        .limit(max(1, min(payload.limit, 20)))
        .all()
    )
    if len(rows) < 2:
        raise HTTPException(status_code=400, detail="Not enough entries yet for a pattern reflection - log a few more first")
 
    entries = [{"body": p.body, "tag_label": p.tag_label} for p in rows]
    try:
        reflection = reflect_on_entry_pattern(client, payload.focus, payload.context_summary, entries)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate a pattern reflection just now - try again. ({e})")
    return {"reflection": reflection, "entries_considered": len(entries)}
 
