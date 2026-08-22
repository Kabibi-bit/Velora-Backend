import os
from fastapi import APIRouter, Depends
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
            ranked = rank_listings(
                [_listing_to_dict(l) for l in listings],
                _profile_to_dict(profile),
                top_n=6,
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
    system = build_system_context(db, payload.user_id)
    messages = payload.history + [{"role": "user", "content": payload.message}]
 
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=system,
        messages=messages,
    )
    reply = "".join(b.text for b in resp.content if b.type == "text")
 
    # Summarize anything durable from this exchange and store it -
    # this is what makes memory persist across sessions, not just within one.
    full_convo = messages + [{"role": "assistant", "content": reply}]
    summary = summarize_conversation(client, full_convo)
    store_memory(db, payload.user_id, summary)
 
    return {"reply": reply}
 
