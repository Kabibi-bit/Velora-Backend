import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
import anthropic
 
from app.db import get_db
from app.models.db_models import SocialPost, Profile, RoadmapSummary
from app.services.social import reflect_on_journal_entry
 
router = APIRouter(prefix="/social", tags=["social"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
def _current_profile(db: Session, user_id: str) -> Profile | None:
    return (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
 
 
class PostIn(BaseModel):
    user_id: str
    body: str
    video_url: str | None = None
    roadmap_stage: int | None = None
    roadmap_stage_title: str | None = None
 
 
@router.post("/posts")
def create_post(payload: PostIn, db: Session = Depends(get_db)):
    """Adds an entry to the user's own private progress journal.
    video_url is a link to wherever the person already hosts their
    video (YouTube, Loom, etc.) - no upload/hosting is done here.
    """
    post = SocialPost(
        user_id=payload.user_id, body=payload.body, video_url=payload.video_url,
        roadmap_stage=payload.roadmap_stage, roadmap_stage_title=payload.roadmap_stage_title,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"post_id": str(post.id), "status": "created"}
 
 
@router.get("/posts/{user_id}")
def list_journal(user_id: str, db: Session = Depends(get_db)):
    """Lists a user's own journal entries, most recent first. This is
    a private journal, not a feed - it never returns another user's
    entries.
    """
    rows = (
        db.query(SocialPost)
        .filter(SocialPost.user_id == user_id)
        .order_by(desc(SocialPost.created_at))
        .limit(100)
        .all()
    )
    return [
        {
            "post_id": str(p.id),
            "body": p.body,
            "video_url": p.video_url,
            "roadmap_stage": p.roadmap_stage,
            "roadmap_stage_title": p.roadmap_stage_title,
            "created_at": p.created_at.isoformat(),
        }
        for p in rows
    ]
 
 
@router.get("/posts/{post_id}/reflect/{user_id}")
def reflect_on_post(post_id: str, user_id: str, db: Session = Depends(get_db)):
    """An honest, specific AI reflection on the user's own journal
    entry, grounded in their real goal and roadmap.
    """
    viewer_profile = _current_profile(db, user_id)
    if not viewer_profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    post = db.query(SocialPost).filter(SocialPost.id == post_id, SocialPost.user_id == user_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Journal entry not found")
 
    roadmap_summary_row = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == user_id).first()
    profile_dict = {"northstar": viewer_profile.northstar, "skills": viewer_profile.skills or ""}
    reflection = reflect_on_journal_entry(
        client, profile_dict,
        roadmap_summary_row.summary if roadmap_summary_row else None,
        post.body, post.roadmap_stage_title,
    )
    return {"post_id": post_id, "reflection": reflection}
 
