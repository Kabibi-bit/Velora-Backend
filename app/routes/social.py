import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
import anthropic
 
from app.db import get_db
from app.models.db_models import SocialPost, SocialComment, SocialConnection, Profile, RoadmapMilestone, RoadmapSummary
from app.services.social import (
    compute_post_relevance_heuristic, compute_connection_relevance_heuristic,
    explain_post_relevance_deep, explain_connection_relevance_deep,
)
 
router = APIRouter(prefix="/social", tags=["social"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
def _current_profile(db: Session, user_id: str) -> Profile | None:
    return (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
 
 
def _profile_dict(p: Profile) -> dict:
    return {"northstar": p.northstar, "skills": p.skills or "", "stage": p.stage or ""}
 
 
# ---------------- Posts ----------------
 
class PostIn(BaseModel):
    user_id: str
    body: str
    video_url: str | None = None
    roadmap_stage: int | None = None
    roadmap_stage_title: str | None = None
 
 
@router.post("/posts")
def create_post(payload: PostIn, db: Session = Depends(get_db)):
    """video_url is a link to wherever the person already hosts their
    video (YouTube, Loom, etc.) - there is no video file upload or
    hosting service connected here. Native video upload would need a
    real object-storage service wired in, the same way real email
    sending needed Resend - intentionally left out rather than faked
    with something that wouldn't actually persist reliably.
    """
    post = SocialPost(
        user_id=payload.user_id, body=payload.body, video_url=payload.video_url,
        roadmap_stage=payload.roadmap_stage, roadmap_stage_title=payload.roadmap_stage_title,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"post_id": str(post.id), "status": "created"}
 
 
@router.get("/feed/{user_id}")
def get_feed(user_id: str, db: Session = Depends(get_db)):
    """Ranked by roadmap/goal relevance to the viewer, not recency or
    engagement - every post returned includes why it's showing up.
    """
    viewer_profile = _current_profile(db, user_id)
    if not viewer_profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    viewer_dict = _profile_dict(viewer_profile)
 
    rows = (
        db.query(SocialPost, Profile)
        .join(Profile, SocialPost.user_id == Profile.user_id)
        .filter(Profile.is_current == True, SocialPost.user_id != user_id)  # noqa: E712
        .order_by(desc(SocialPost.created_at))
        .limit(100)
        .all()
    )
 
    scored = []
    for post, author_profile in rows:
        author_dict = _profile_dict(author_profile)
        relevance = compute_post_relevance_heuristic(viewer_dict, post.body, author_dict)
        scored.append({
            "post_id": str(post.id),
            "author_goal": author_profile.northstar,
            "body": post.body,
            "video_url": post.video_url,
            "roadmap_stage": post.roadmap_stage,
            "roadmap_stage_title": post.roadmap_stage_title,
            "created_at": post.created_at.isoformat(),
            "relevance_score": relevance["score"],
            "matched_topic_terms": relevance["matched_topic_terms"],
            "same_goal_direction": relevance["same_goal_direction"],
        })
    scored.sort(key=lambda p: p["relevance_score"], reverse=True)
    return {"feed": scored}
 
 
@router.get("/posts/{post_id}/explain/{viewer_id}")
def explain_post(post_id: str, viewer_id: str, db: Session = Depends(get_db)):
    viewer_profile = _current_profile(db, viewer_id)
    if not viewer_profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    author_profile = _current_profile(db, str(post.user_id))
    if not author_profile:
        raise HTTPException(status_code=404, detail="Post author has no current profile")
 
    roadmap_summary_row = db.query(RoadmapSummary).filter(RoadmapSummary.user_id == viewer_id).first()
    explanation = explain_post_relevance_deep(
        client, _profile_dict(viewer_profile),
        roadmap_summary_row.summary if roadmap_summary_row else None,
        post.body, _profile_dict(author_profile),
    )
    return {"post_id": post_id, "explanation": explanation}
 
 
# ---------------- Comments ----------------
 
class CommentIn(BaseModel):
    user_id: str
    body: str
 
 
@router.post("/posts/{post_id}/comments")
def add_comment(post_id: str, payload: CommentIn, db: Session = Depends(get_db)):
    post = db.query(SocialPost).filter(SocialPost.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    comment = SocialComment(post_id=post_id, user_id=payload.user_id, body=payload.body)
    db.add(comment)
    db.commit()
    return {"status": "created"}
 
 
@router.get("/posts/{post_id}/comments")
def get_comments(post_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(SocialComment)
        .filter(SocialComment.post_id == post_id)
        .order_by(SocialComment.created_at)
        .all()
    )
    return [{"id": str(c.id), "body": c.body, "created_at": c.created_at.isoformat()} for c in rows]
 
 
# ---------------- Connections ----------------
 
class ConnectionRequestIn(BaseModel):
    requester_id: str
    target_id: str
 
 
@router.post("/connections/request")
def request_connection(payload: ConnectionRequestIn, db: Session = Depends(get_db)):
    if payload.requester_id == payload.target_id:
        raise HTTPException(status_code=400, detail="Cannot connect with yourself")
    existing = (
        db.query(SocialConnection)
        .filter(SocialConnection.requester_id == payload.requester_id, SocialConnection.target_id == payload.target_id)
        .first()
    )
    if existing:
        return {"status": existing.status, "already_existed": True}
    conn = SocialConnection(requester_id=payload.requester_id, target_id=payload.target_id)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return {"connection_id": str(conn.id), "status": "pending"}
 
 
class RespondIn(BaseModel):
    status: str
 
 
@router.post("/connections/{connection_id}/respond")
def respond_connection(connection_id: str, payload: RespondIn, db: Session = Depends(get_db)):
    if payload.status not in {"accepted", "declined"}:
        raise HTTPException(status_code=400, detail="status must be 'accepted' or 'declined'")
    conn = db.query(SocialConnection).filter(SocialConnection.id == connection_id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection request not found")
    conn.status = payload.status
    db.commit()
    return {"status": conn.status}
 
 
@router.get("/connections/{user_id}")
def list_connections(user_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(SocialConnection)
        .filter(
            ((SocialConnection.requester_id == user_id) | (SocialConnection.target_id == user_id)),
            SocialConnection.status == "accepted",
        )
        .all()
    )
    return [{"connection_id": str(c.id), "with_user_id": str(c.target_id if str(c.requester_id) == user_id else c.requester_id)} for c in rows]
 
 
@router.get("/connections/{user_id}/suggested")
def suggested_connections(user_id: str, db: Session = Depends(get_db)):
    viewer_profile = _current_profile(db, user_id)
    if not viewer_profile:
        raise HTTPException(status_code=404, detail="No current profile for this user")
    viewer_dict = _profile_dict(viewer_profile)
 
    existing_ids = {
        str(c.target_id if str(c.requester_id) == user_id else c.requester_id)
        for c in db.query(SocialConnection).filter(
            (SocialConnection.requester_id == user_id) | (SocialConnection.target_id == user_id)
        ).all()
    }
 
    candidates = (
        db.query(Profile)
        .filter(Profile.is_current == True, Profile.user_id != user_id)  # noqa: E712
        .all()
    )
    scored = []
    for target_profile in candidates:
        if str(target_profile.user_id) in existing_ids:
            continue
        target_dict = _profile_dict(target_profile)
        relevance = compute_connection_relevance_heuristic(viewer_dict, target_dict)
        scored.append({
            "user_id": str(target_profile.user_id),
            "goal": target_profile.northstar,
            "stage": target_profile.stage,
            "relevance_score": relevance["score"],
            "matched_terms": relevance["matched_terms"],
            "stage_relation": relevance["stage_relation"],
        })
    scored.sort(key=lambda c: c["relevance_score"], reverse=True)
    return {"suggested": scored[:10]}
 
 
@router.get("/connections/{user_id}/explain/{target_id}")
def explain_connection(user_id: str, target_id: str, db: Session = Depends(get_db)):
    viewer_profile = _current_profile(db, user_id)
    target_profile = _current_profile(db, target_id)
    if not viewer_profile or not target_profile:
        raise HTTPException(status_code=404, detail="Profile not found for viewer or target")
    explanation = explain_connection_relevance_deep(client, _profile_dict(viewer_profile), _profile_dict(target_profile))
    return {"target_id": target_id, "explanation": explanation}
 
