"""Real auto-apply logic: drafts an application via Claude, decides
whether it's confident enough to auto-send or needs human review,
and enforces an undo window before anything is considered final.
 
Honest limitation: there is no real mechanism here that actually
submits a form on a real job site -- send_application() marks the
record as "sent" in your own database, it does not reach out to
Adzuna or any employer's website. Building a real submission bot is
a much larger, higher-risk project (site-specific automation, ToS
review per site) intentionally left out of this version.
"""
import os
from datetime import datetime, timedelta
 
CONFIDENCE_THRESHOLD = int(os.getenv("AUTO_APPLY_THRESHOLD", "80"))
UNDO_WINDOW_MINUTES = int(os.getenv("UNDO_WINDOW_MINUTES", "30"))
 
 
def draft_application(anthropic_client, listing: dict, profile: dict) -> str:
    prompt = (
        f"Write a short, tailored cover-letter-style paragraph (120-180 words) "
        f"for this listing: \"{listing['title']}\" at {listing['org']}.\n"
        f"Candidate's goal: \"{profile['northstar']}\"\n"
        f"Candidate's skills: \"{profile.get('skills', '')}\"\n"
        "Be concrete and specific, no generic filler, no placeholder brackets."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
 
 
def decide_auto_send(confidence_pct: float) -> str:
    """Returns 'approved' (auto-send eligible) or 'pending_review'."""
    return "approved" if confidence_pct >= CONFIDENCE_THRESHOLD else "pending_review"
 
 
def compute_sendable_at() -> datetime:
    """The undo window: even an approved application isn't 'sent' until
    this time passes, giving a window to cancel."""
    return datetime.utcnow() + timedelta(minutes=UNDO_WINDOW_MINUTES)
 
