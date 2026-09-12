import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import Profile
from app.services.chat_memory import (
    summarize_conversation,
    store_memory,
    retrieve_relevant_memory,
)
from app.services.matching import rank_listings
from app.routes.listings import _profile_to_dict, _listing_to_dict
from app.models.db_models import Listing
 
router = APIRouter(prefix="/chat", tags=["chat"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class ChatIn(BaseModel):
    user_id: str
    message: str
    history: list[dict] = []
 
 
def build_system_context(db: Session, user_id: str) -> str:
    """Pulls the user's real profile, live top matches, and remembered
    facts from past conversations into one system prompt.
    """
    base = (
        "You are the assistant inside Scanline, an internship/job/college "
        "opportunity watch app. Answer questions about internships, job "
        "searching, applications, resumes, and career strategy. Be concise "
        "and practical."
    )
 
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user_id, Profile.is_current == True)  # noqa: E712
        .first()
    )
    if profile:
        base += (
            f"\n\nThe user's stated goal: \"{profile.northstar}\". "
            f"Timeframe: {profile.timeframe}. Stage: {profile.stage}. "
            f"Priorities: {', '.join(profile.priorities or [])}. "
            f"Skills: \"{profile.skills}\"."
        )
        listings = db.query(Listing).all()
        if listings:
            from app.models.db_models import DismissedListing
            dismissed_ids = {str(row.listing_id) for row in db.query(DismissedListing).filter(DismissedListing.user_id == user_id).all()}
            ranked = rank_listings(
                [_listing_to_dict(l) for l in listings],
                _profile_to_dict(profile),
                top_n=6,
                dismissed_ids=dismissed_ids,
            )
            if ranked:
                base += "\n\nTheir current top matches:\n"
                for l in ranked:
                    base += f"- {l['title']} at {l['org']} ({l['score_pct']}% match, due {l['deadline']})\n"
 
    memories = retrieve_relevant_memory(db, user_id)
    if memories:
        base += "\n\nThings you remember about this user from past conversations:\n"
        base += "\n".join(f"- {m}" for m in memories)
 
    return base
 
 
@router.post("")
def chat(payload: ChatIn, db: Session = Depends(get_db)):
    import uuid as uuid_module
    try:
        uuid_module.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id is not a valid UUID")
    system = build_system_context(db, payload.user_id)
    messages = payload.history + [{"role": "user", "content": payload.message}]
 
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system,
            messages=messages,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not get a reply just now - try again. ({e})")
    reply = "".join(b.text for b in resp.content if b.type == "text")
 
    # Summarize anything durable from this exchange and store it -
    # this is what makes memory persist across sessions, not just within one.
    full_convo = messages + [{"role": "assistant", "content": reply}]
    try:
        summary = summarize_conversation(client, full_convo)
        store_memory(db, payload.user_id, summary)
    except Exception as e:
        # A real reply was already generated above - a failure here
        # (summarization API call, or the DB write) must not discard
        # that and turn a successful chat into an error response. The
        # person still gets their real reply; only future-session
        # memory of this exchange is honestly lost, not the exchange
        # itself.
        print(f"Chat memory summarization/storage failed (non-fatal, reply still returned): {e}")
 
    return {"reply": reply}
 
